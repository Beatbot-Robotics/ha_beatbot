"""WebSocket event stream for incremental Beatbot cloud state updates."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import logging
import random

from aiohttp import ClientError
from beatbot_cloud import (
    BeatbotAuthenticationError,
    BeatbotConnectionError,
    BeatbotConnectionReplacedError,
    BeatbotEvent,
    BeatbotEventStream,
    BeatbotTokenRejectedError,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from ..api import BeatbotAPI
from ..coordinator import BeatbotCoordinator
from .const import (
    DOMAIN,
    EVENT_DEDUP_CACHE_SIZE,
    EVENT_HEARTBEAT_INTERVAL,
    EVENT_HEARTBEAT_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

_RECONNECT_DELAYS = (1.0, 2.0, 4.0, 8.0, 30.0, 60.0)
_RECONNECT_JITTER = 0.2


_ConnectionReplaced = BeatbotConnectionReplacedError
_RefreshToken = BeatbotTokenRejectedError


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
        self._stream: BeatbotEventStream | None = None
        self._stopping = False
        self._handshake_refresh_attempted = False
        self._has_connected = False
        self._seen_event_ids: OrderedDict[str, None] = OrderedDict()
        self._reload_scheduled = False

    def async_start(self) -> None:
        """Start the connection supervisor without blocking setup."""
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = self._entry.async_create_background_task(
                self._hass,
                self._run(),
                f"beatbot_event_stream_{self._entry.entry_id}",
            )

    async def async_stop(self) -> None:
        """Stop and close the stream. Safe to call repeatedly."""
        self._stopping = True
        if self._stream is not None:
            await self._stream.close()
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
                except (BeatbotAuthenticationError, ConfigEntryAuthFailed):
                    _LOGGER.warning(
                        "Beatbot event stream authorization failed; "
                        "starting reauthentication"
                    )
                    self._entry.async_start_reauth(self._hass)
                    return
                except (
                    BeatbotConnectionError,
                    ClientError,
                    asyncio.TimeoutError,
                    ConnectionError,
                ) as err:
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
            _LOGGER.warning("Beatbot token refresh failed; starting reauthentication")
            self._entry.async_start_reauth(self._hass)
        finally:
            await self._async_close_connection()

    async def _async_refresh_token_once(self, rejected_access_token: str) -> None:
        """Refresh a rejected token through the session's shared rotation lock."""
        # OAuth2Session uses this lock for REST-triggered automatic refreshes.
        # Sharing it here is essential when refresh-token rotation is enabled:
        # two independent refreshes with the same token would invalidate one
        # another and leave HA holding a refresh token the server no longer
        # accepts. HA 2025.4 (our minimum) and current HA expose this lock.
        async with self._oauth_session._token_lock:
            current_token = self._oauth_session.token
            if current_token.get("access_token") != rejected_access_token:
                _LOGGER.debug(
                    "Skipping Beatbot OAuth refresh for an already replaced token "
                    "(entry_id=%s)",
                    self._entry.entry_id,
                )
                return
            try:
                new_token = (
                    await self._oauth_session.implementation.async_refresh_token(
                        current_token
                    )
                )
            except Exception as err:
                _LOGGER.warning(
                    "Beatbot OAuth refresh after event stream rejection failed "
                    "(entry_id=%s): %s",
                    self._entry.entry_id,
                    err,
                )
                raise ConfigEntryAuthFailed from err
            self._hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, "token": new_token},
            )
            _LOGGER.info(
                "Beatbot OAuth token rotated after event stream rejection "
                "(entry_id=%s)",
                self._entry.entry_id,
            )

    async def _connect_and_receive(self) -> None:
        await self._oauth_session.async_ensure_token_valid()
        token = self._oauth_session.token.get("access_token")
        if not token:
            raise ConfigEntryAuthFailed("OAuth token has no access_token")

        stream = BeatbotEventStream(
            async_get_clientsession(self._hass),
            self._api.event_stream_url,
            token,
            heartbeat=EVENT_HEARTBEAT_INTERVAL,
            receive_timeout=EVENT_HEARTBEAT_TIMEOUT,
        )
        self._stream = stream
        try:
            await stream.connect()
            self._handshake_refresh_attempted = False
            is_reconnect = self._has_connected
            self._has_connected = True
            _LOGGER.debug(
                "Connected to Beatbot event stream at %s", self._api.event_stream_url
            )
            if is_reconnect:
                await self._coordinator.async_request_refresh()
            while not self._stopping:
                self._handle_event(await stream.receive())
        finally:
            await stream.close()
            if self._stream is stream:
                self._stream = None

    @staticmethod
    def _raise_for_close_code(
        code: int | None, access_token: str, error: BaseException | None
    ) -> None:
        """Translate server close codes into supervisor actions."""
        _LOGGER.warning(
            "Beatbot event stream closed closeCode=%s deviceId=unknown", code
        )
        stream = object.__new__(BeatbotEventStream)
        stream._access_token = access_token
        try:
            stream._raise_for_close_code(code, error)
        except BeatbotTokenRejectedError:
            raise
        except BeatbotAuthenticationError as err:
            raise ConfigEntryAuthFailed from err

    async def _async_close_connection(self) -> None:
        """Close and discard the current connection."""
        stream, self._stream = self._stream, None
        if stream is not None:
            await stream.close()

    def _handle_text_message(self, raw: str) -> None:
        """Parse and dispatch one text event."""
        try:
            self._handle_event(BeatbotEventStream.parse_event(raw))
        except BeatbotConnectionError as err:
            _LOGGER.warning("Ignoring malformed Beatbot event: %s", err)

    def _handle_event(self, event: BeatbotEvent) -> None:
        """Apply one validated event to Home Assistant state."""
        try:
            event_id = event.event_id
            event_type = event.event_type
            device_id = event.device_id
            payload = event.payload
            if event_id in self._seen_event_ids:
                return
            self._remember_event(event_id)
            _LOGGER.info(
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
            elif event_type == "device_added":
                payload_device_id = payload.get("deviceId")
                if payload_device_id != device_id:
                    raise ValueError(
                        "device_added payload deviceId does not match event deviceId"
                    )
                self._schedule_entry_reload()
            elif event_type == "device_removed":
                self._remove_device_from_registries(device_id)
                self._schedule_entry_reload()
            else:
                _LOGGER.debug("Ignoring unknown Beatbot event type %s", event_type)
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Ignoring malformed Beatbot event: %s", err)

    def _schedule_entry_reload(self) -> None:
        """Reload all platforms after the account's device set changes."""
        if self._reload_scheduled or self._stopping:
            return
        self._reload_scheduled = True

        async def _reload() -> None:
            try:
                await self._hass.config_entries.async_reload(self._entry.entry_id)
            finally:
                self._reload_scheduled = False

        self._hass.async_create_task(
            _reload(), f"beatbot_reload_{self._entry.entry_id}"
        )

    def _remove_device_from_registries(self, device_id: str) -> None:
        """Remove entities and the device registry entry after account removal."""
        device_registry = dr.async_get(self._hass)
        device = device_registry.async_get_device(identifiers={(DOMAIN, device_id)})
        if device is None:
            return

        entity_registry = er.async_get(self._hass)
        for entity in er.async_entries_for_device(
            entity_registry, device.id, include_disabled_entities=True
        ):
            if entity.config_entry_id == self._entry.entry_id:
                entity_registry.async_remove(entity.entity_id)
        device_registry.async_remove_device(device.id)

    def _remember_event(self, event_id: str) -> None:
        self._seen_event_ids[event_id] = None
        self._seen_event_ids.move_to_end(event_id)
        while len(self._seen_event_ids) > EVENT_DEDUP_CACHE_SIZE:
            self._seen_event_ids.popitem(last=False)
