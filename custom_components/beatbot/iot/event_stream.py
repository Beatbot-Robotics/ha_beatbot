"""WebSocket event stream for incremental Beatbot cloud state updates."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import json
import logging
import random

from aiohttp import ClientError, ClientWebSocketResponse, WSMsgType, WSServerHandshakeError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..api import BeatbotAPI
from ..coordinator import BeatbotCoordinator
from .const import (
    EVENT_DEDUP_CACHE_SIZE,
    EVENT_HEARTBEAT_INTERVAL,
    EVENT_HEARTBEAT_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

_RECONNECT_DELAYS = (1.0, 2.0, 4.0, 8.0, 30.0, 60.0)
_RECONNECT_JITTER = 0.2


class _ConnectionReplaced(Exception):
    """The server replaced this connection with a newer one."""


class _RefreshToken(Exception):
    """The server rejected the access token."""

    def __init__(self, access_token: str, *, handshake: bool = False) -> None:
        super().__init__("access token rejected")
        self.access_token = access_token
        self.handshake = handshake


class BeatbotEventClient:
    """Maintain the account-scoped cloud event WebSocket."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        oauth_session: config_entry_oauth2_flow.OAuth2Session,
        api: BeatbotAPI,
        coordinator: BeatbotCoordinator,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._oauth_session = oauth_session
        self._api = api
        self._coordinator = coordinator
        self._task: asyncio.Task[None] | None = None
        self._ws: ClientWebSocketResponse | None = None
        self._stopping = False
        self._token_refresh_lock = asyncio.Lock()
        self._handshake_refresh_attempted = False
        self._seen_event_ids: OrderedDict[str, None] = OrderedDict()

    def async_start(self) -> None:
        """Start the connection supervisor without blocking setup."""
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = self._hass.async_create_task(
                self._run(), f"beatbot_event_stream_{self._entry.entry_id}"
            )

    async def async_stop(self) -> None:
        """Stop and close the stream. Safe to call repeatedly."""
        self._stopping = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        task, self._task = self._task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        failures = 0
        try:
            while not self._stopping:
                try:
                    await self._connect_and_receive()
                except asyncio.CancelledError:
                    raise
                except _ConnectionReplaced:
                    # 4002 is terminal. Reconnecting would make multiple HA
                    # instances continuously evict one another.
                    return
                except _RefreshToken as err:
                    if err.handshake and self._handshake_refresh_attempted:
                        raise ConfigEntryAuthFailed(
                            "WebSocket handshake still unauthorized after token refresh"
                        ) from err
                    await self._async_refresh_token_once(err.access_token)
                    if err.handshake:
                        self._handshake_refresh_attempted = True
                    failures = 0
                    continue
                except ConfigEntryAuthFailed:
                    _LOGGER.warning(
                        "Beatbot event stream authorization failed; "
                        "starting reauthentication"
                    )
                    self._entry.async_start_reauth(self._hass)
                    return
                except (ClientError, asyncio.TimeoutError, ConnectionError) as err:
                    failures += 1
                    _LOGGER.warning("Beatbot event stream disconnected: %s", err)
                except Exception:
                    failures += 1
                    _LOGGER.exception("Unexpected Beatbot event stream failure")

                if self._stopping:
                    return
                delay = _RECONNECT_DELAYS[min(failures - 1, len(_RECONNECT_DELAYS) - 1)]
                delay *= random.uniform(
                    1.0 - _RECONNECT_JITTER, 1.0 + _RECONNECT_JITTER
                )
                await asyncio.sleep(delay)
        except ConfigEntryAuthFailed:
            _LOGGER.warning(
                "Beatbot token refresh failed; starting reauthentication"
            )
            self._entry.async_start_reauth(self._hass)
        finally:
            await self._async_close_connection()

    async def _async_refresh_token_once(self, rejected_access_token: str) -> None:
        """Refresh a rejected token, coalescing concurrent refresh requests."""
        async with self._token_refresh_lock:
            current_token = self._oauth_session.token
            if current_token.get("access_token") != rejected_access_token:
                return
            try:
                new_token = await self._oauth_session.implementation.async_refresh_token(
                    current_token
                )
            except Exception as err:
                raise ConfigEntryAuthFailed from err
            self._hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, "token": new_token},
            )

    async def _connect_and_receive(self) -> None:
        await self._oauth_session.async_ensure_token_valid()
        token = self._oauth_session.token.get("access_token")
        if not token:
            raise ConfigEntryAuthFailed("OAuth token has no access_token")

        client = async_get_clientsession(self._hass)
        try:
            async with client.ws_connect(
                self._api.event_stream_url,
                headers={"Authorization": f"Bearer {token}"},
                heartbeat=EVENT_HEARTBEAT_INTERVAL,
                autoping=True,
            ) as ws:
                self._ws = ws
                # A completed upgrade proves that the refreshed token was
                # accepted. A future handshake 401 may therefore use one new
                # refresh attempt.
                self._handshake_refresh_attempted = False
                _LOGGER.debug("Connected to Beatbot event stream")
                while not self._stopping:
                    message = await ws.receive(timeout=EVENT_HEARTBEAT_TIMEOUT)
                    if message.type is WSMsgType.TEXT:
                        self._handle_text_message(message.data)
                    elif message.type in (
                        WSMsgType.CLOSE,
                        WSMsgType.CLOSED,
                        WSMsgType.ERROR,
                    ):
                        error = ws.exception()
                        self._raise_for_close_code(ws.close_code, token, error)
        except WSServerHandshakeError as err:
            if err.status == 401:
                raise _RefreshToken(token, handshake=True) from err
            if err.status == 403:
                raise ConfigEntryAuthFailed from err
            raise
        finally:
            if self._ws is not None and not self._ws.closed:
                await self._ws.close()
            self._ws = None

    @staticmethod
    def _raise_for_close_code(
        code: int | None, access_token: str, error: BaseException | None
    ) -> None:
        """Translate server close codes into supervisor actions."""
        _LOGGER.warning(
            "Beatbot event stream closed closeCode=%s deviceId=unknown", code
        )
        if code == 4001:
            raise _RefreshToken(access_token) from error
        if code == 4002:
            raise _ConnectionReplaced from error
        if code == 4003:
            raise ConfigEntryAuthFailed from error
        raise ConnectionError(f"WebSocket closed with code {code}") from error

    async def _async_close_connection(self) -> None:
        """Close and discard the current connection."""
        ws, self._ws = self._ws, None
        if ws is not None and not ws.closed:
            await ws.close()

    def _handle_text_message(self, raw: str) -> None:
        try:
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise ValueError("event is not an object")
            event_id = event.get("eventId")
            event_type = event.get("type")
            device_id = event.get("deviceId")
            payload = event.get("payload")
            if not all(isinstance(value, str) and value for value in (
                event_id, event_type, device_id
            )) or not isinstance(payload, dict):
                raise ValueError("missing eventId, type, deviceId, or payload")

            if event_id in self._seen_event_ids:
                return
            self._remember_event(event_id)
            _LOGGER.debug(
                "Received Beatbot event eventId=%s deviceId=%s type=%s",
                event_id,
                device_id,
                event_type,
            )

            if event_type == "properties_changed":
                interface_info = payload.get("interfaceInfo")
                if not isinstance(interface_info, str) or not interface_info:
                    raise ValueError("property event has no interfaceInfo")
                self._coordinator.async_apply_device_event(
                    device_id, {interface_info: payload.get("value")}
                )
            elif event_type == "status":
                online = payload.get("online")
                if not isinstance(online, bool):
                    raise ValueError("status event has no boolean online value")
                self._coordinator.async_apply_device_event(
                    device_id, None, is_online=online
                )
            else:
                _LOGGER.debug("Ignoring unknown Beatbot event type %s", event_type)
        except (json.JSONDecodeError, ValueError, TypeError) as err:
            _LOGGER.warning("Ignoring malformed Beatbot event: %s", err)

    def _remember_event(self, event_id: str) -> None:
        self._seen_event_ids[event_id] = None
        self._seen_event_ids.move_to_end(event_id)
        while len(self._seen_event_ids) > EVENT_DEDUP_CACHE_SIZE:
            self._seen_event_ids.popitem(last=False)
