"""Beatbot cloud API client.

Targets the device-resource-service (OAuth2 resource server). The gateway
forwards /device_resource/** without Signature/Authentic filters, so standard
`Authorization: Bearer <jwt>` (added by OAuth2Session) is all that is needed.

The HA discovery endpoint (`/devices/ha`) returns a `HaDiscoveryResult` object
(`{"devices": [...]}`) carrying device identity, product info and capability
mappings only — no runtime state. Runtime state must be fetched separately via
`/devices/state/{deviceId}`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import ClientTimeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .iot.const import (
    BEATBOT_API_DEVICE_ACTIONS_PATH,
    BEATBOT_API_DEVICES_PATH,
    BEATBOT_API_EVENTS_PATH,
    BEATBOT_API_DEVICE_STATES_PATH,
    BEATBOT_HTTP_API_TIMEOUT,
    INTERFACE_WORK_MODE,
    REGION_API_BASE_URL,
    RESULT_SUCCESS_CODE,
)
from .models import BeatbotCapability, BeatbotDeviceData, FirmwareVersion

_LOGGER = logging.getLogger(__name__)


class BeatbotAuthError(Exception):
    """Raised when the request is rejected as unauthorized."""


class BeatbotConnectionError(Exception):
    """Raised when the API cannot be reached or returns an error."""


class BeatbotAPI:
    """Beatbot API client backed by an OAuth2Session (auto-refreshing token)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session: config_entry_oauth2_flow.OAuth2Session,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._session = session
        region = entry.data.get("region")
        # No fallback: a missing or unmapped region must fail loudly rather
        # than silently route traffic to the wrong backend. The config flow
        # validates this upfront; this guard defends against stale entries.
        if region not in REGION_API_BASE_URL:
            raise ValueError(f"Unknown or missing Beatbot region: {region!r}")
        self._base_url = REGION_API_BASE_URL[region]


    @property
    def event_stream_url(self) -> str:
        """Return the region-routed WebSocket endpoint."""
        if self._base_url.startswith("https://"):
            base_url = f"wss://{self._base_url.removeprefix('https://')}"
        else:
            base_url = self._base_url
        return f"{base_url}{BEATBOT_API_EVENTS_PATH}"

    async def _request(
        self, method: str, path: str, *, params: dict[str, str] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        try:
            resp = await self._session.async_request(
                method, url, params=params, json=json_body,
                headers={"Accept": "application/json"},
                timeout=ClientTimeout(total=BEATBOT_HTTP_API_TIMEOUT),
            )
        except Exception as err:
            raise BeatbotConnectionError(str(err)) from err

        if resp.status in (401, 403):
            body = await resp.text()
            _LOGGER.warning(
                "Beatbot API %s %s rejected (%s): %s",
                method, path, resp.status, body[:500],
            )
            raise BeatbotAuthError(f"Unauthorized: {resp.status}")

        if resp.status >= 400:
            body = await resp.text()
            _LOGGER.warning(
                "Beatbot API %s %s failed (%s): %s",
                method, path, resp.status, body[:500],
            )
            raise BeatbotConnectionError(f"API request failed: {resp.status}")

        body = await resp.text()
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as err:
            content_type = resp.headers.get("Content-Type", "unknown")
            _LOGGER.warning(
                "Beatbot API %s %s returned non-JSON response (%s, %s): %s",
                method, path, resp.status, content_type, body[:500],
            )
            raise BeatbotConnectionError(
                "API returned non-JSON response "
                f"({resp.status}, {content_type})"
            ) from err

        if not isinstance(payload, dict):
            raise BeatbotConnectionError("API returned an invalid response envelope")

        if payload.get("code") != RESULT_SUCCESS_CODE:
            raise BeatbotConnectionError(
                f"API error {payload.get('code')}: {payload.get('message')}"
            )
        return payload.get("data")

    async def get_devices(self) -> list[BeatbotDeviceData]:
        """Return the user's discovered devices from the HA discovery endpoint.

        The endpoint returns a Result envelope wrapping a `HaDiscoveryResult`
        object: data = {"devices": [{deviceId, productId, productCategory,
        isOnline, ...}]}. Runtime state (work status, battery, etc.) is not
        included and must be fetched via `/devices/state/{deviceId}`.
        """
        raw = await self._request("GET", BEATBOT_API_DEVICES_PATH)
        if not raw:
            return []
        # `data` is a JSON object for the HA endpoint; keep the string fallback
        # in case a gateway hop stringifies the payload.
        if isinstance(raw, str):
            try:
                discovery = json.loads(raw)
            except (json.JSONDecodeError, TypeError) as err:
                raise BeatbotConnectionError(
                    f"Invalid discovery payload: {err}"
                ) from err
        else:
            discovery = raw

        devices = (discovery or {}).get("devices") or []
        result: list[BeatbotDeviceData] = []
        for device in devices:
            parsed = self._parse_device(device)
            if parsed is not None:
                result.append(parsed)
        return result

    @staticmethod
    def _parse_device(device: dict[str, Any]) -> BeatbotDeviceData | None:
        device_id = device.get("deviceId") or ""
        if not device_id:
            return None
        versions = [
            FirmwareVersion(
                channel=v.get("channel", 0),
                version=v.get("version") or "",
            )
            for v in (device.get("versions") or [])
            if isinstance(v, dict)
        ]
        return BeatbotDeviceData(
            device_id=device_id,
            product_id=device.get("productId") or "",
            product_category=device.get("productCategory") or "",
            name=device.get("name") or "",
            model=device.get("model") or "",
            work_status=0,
            work_mode=0,
            error_code=0,
            battery_level=0,
            versions=versions,
            is_online=bool(device.get("isOnline", False)),
            work_mode_options=BeatbotAPI._parse_work_mode_options(
                device.get("capabilities")
            ),
            capabilities=BeatbotAPI._parse_capabilities(
                device.get("capabilities")
            ),
        )

    @staticmethod
    def _parse_work_mode_options(
        capabilities: list[dict[str, Any]] | None,
    ) -> dict[int, str]:
        """Extract the per-device work-mode value->label map.

        The `select.work_mode` capability carries a JSON `configuration`
        string: {"options":[{"label":"fast","value":0}, ...]}. Values are not
        sequential (e.g. 0,2,3,4,7), so the map must be data-driven, not
        index-based.
        """
        for cap in capabilities or []:
            if cap.get("interfaceInfo") != INTERFACE_WORK_MODE:
                continue
            cfg = cap.get("configuration")
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except (json.JSONDecodeError, TypeError):
                    cfg = None
            if not isinstance(cfg, dict):
                return {}
            options: dict[int, str] = {}
            for opt in cfg.get("options") or []:
                value = opt.get("value")
                label = opt.get("label")
                if value is not None and label:
                    options[value] = label
            return options
        return {}

    @staticmethod
    def _parse_capabilities(
        capabilities: list[dict[str, Any]] | None,
    ) -> dict[str, BeatbotCapability]:
        """Parse the discovery `capabilities` array into a keyed map.

        Keyed by `interfaceInfo` (e.g. "vacuum.start"). Drives dynamic vacuum
        feature derivation. Malformed entries (non-dict or missing
        `interfaceInfo`) are skipped rather than aborting discovery.
        """
        parsed: dict[str, BeatbotCapability] = {}
        for cap in capabilities or []:
            if not isinstance(cap, dict):
                continue
            interface_info = cap.get("interfaceInfo")
            if not interface_info:
                continue
            parsed[interface_info] = BeatbotCapability(
                interface_info=interface_info,
                retrievable=bool(cap.get("retrievable", False)),
                proactively_reported=bool(cap.get("proactivelyReported", False)),
                non_controllable=bool(cap.get("nonControllable", False)),
            )
        return parsed

    async def get_device_states(self) -> dict[str, dict]:
        """Return batched runtime state for all devices.

        Hits the HA batch state endpoint and returns
        `{deviceId: {"is_online": bool|None, "states": {interfaceInfo: value}}}`.
        Identity (device list) comes from `get_devices`; this call only carries
        runtime values keyed by HA `interfaceInfo`.
        """
        raw = await self._request(
            "GET",
            BEATBOT_API_DEVICE_STATES_PATH
        )
        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        else:
            payload = raw
        devices = (payload or {}).get("devices") or []
        return {
            d["deviceId"]: {
                "is_online": d.get("isOnline"),
                "states": d.get("states") or {},
            }
            for d in devices
            if d.get("deviceId")
        }

    async def get_device_state(self, device_id: str) -> dict:
        """Return runtime state for a single device.

        Hits `GET /devices/{deviceId}/state`; the `data` field is one device
        bean (same shape as an entry in the batch `devices` array):
        `{deviceId, isOnline, states}`. Returns
        `{"is_online": bool|None, "states": {interfaceInfo: value}}`.
        """
        raw = await self._request(
            "GET",
            f"{BEATBOT_API_DEVICE_ACTIONS_PATH}/{device_id}/state",
        )
        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        else:
            payload = raw
        if not isinstance(payload, dict):
            return {}
        return {
            "is_online": payload.get("isOnline"),
            "states": payload.get("states") or {},
        }

    async def send_action(self, device_id: str, interface_info: str) -> None:
        """Issue a parameterless action by its interfaceInfo key."""
        await self._request(
            "POST",
            f"{BEATBOT_API_DEVICE_ACTIONS_PATH}/{device_id}/actions",
            json_body={"interfaceInfo": interface_info},
        )

    async def set_work_mode(self, device_id: str, label: str) -> None:
        """Set the device work mode via the `select.work_mode` capability.

        `label` is the human-readable option string advertised in the
        capability's `configuration.options` (the same one the select entity
        shows to the user). The backend resolves the target mode from the
        label alone — the integer `value` is not sent in the action body.
        """
        await self._request(
            "POST",
            f"{BEATBOT_API_DEVICE_ACTIONS_PATH}/{device_id}/actions",
            json_body={
                "interfaceInfo": INTERFACE_WORK_MODE,
                "label": label,
            },
        )

    async def set_switch(
        self, device_id: str, interface_info: str, label: str
    ) -> None:
        """Set an on/off switch capability."""
        await self._request(
            "POST",
            f"{BEATBOT_API_DEVICE_ACTIONS_PATH}/{device_id}/actions",
            json_body={
                "interfaceInfo": interface_info,
                "label": label,
            },
        )
