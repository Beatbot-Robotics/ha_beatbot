"""Beatbot cloud API client.

Targets the device-resource-service (OAuth2 resource server). The gateway
forwards /device_resource/** without Signature/Authentic filters, so standard
`Authorization: Bearer <jwt>` (added by OAuth2Session) is all that is needed.
The discovery endpoint returns an Alexa-style `{"endpoints": [...]}` payload.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .iot.const import (
    BEATBOT_API_BASE_URL,
    BEATBOT_API_DEVICE_ACTIONS_PATH,
    BEATBOT_API_DEVICES_PATH,
    BEATBOT_API_PLATFORM,
    RESULT_SUCCESS_CODE,
)
from .models import BeatbotDeviceData

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

    async def _request(
        self, method: str, path: str, *, params: dict[str, str] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        url = f"{BEATBOT_API_BASE_URL}{path}"
        try:
            resp = await self._session.async_request(
                method, url, params=params, json=json_body
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

        try:
            payload = await resp.json()
        except Exception as err:
            raise BeatbotConnectionError(f"Failed to decode response: {err}") from err

        if payload.get("code") != RESULT_SUCCESS_CODE:
            raise BeatbotConnectionError(
                f"API error {payload.get('code')}: {payload.get('message')}"
            )
        return payload.get("data")

    async def get_devices(self) -> list[BeatbotDeviceData]:
        """Return the user's discovered devices.

        The endpoint returns a JSON string (Alexa discovery format) wrapped in
        the Result envelope, e.g. data = '{"endpoints":[{...}]}'.
        """
        import json

        raw = await self._request(
            "GET", BEATBOT_API_DEVICES_PATH,
            params={"platform": BEATBOT_API_PLATFORM},
        )
        if not raw:
            return []
        try:
            discovery = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError) as err:
            raise BeatbotConnectionError(f"Invalid discovery payload: {err}") from err

        endpoints = discovery.get("endpoints") or []
        result: list[BeatbotDeviceData] = []
        for endpoint in endpoints:
            device = self._parse_endpoint(endpoint)
            if device is not None:
                result.append(device)
        return result

    @staticmethod
    def _parse_endpoint(endpoint: dict[str, Any]) -> BeatbotDeviceData | None:
        device_id = endpoint.get("endpointId")
        if not device_id:
            return None
        categories = endpoint.get("display_categories") or endpoint.get("displayCategories") or []
        additional = endpoint.get("additionalAttributes") or {}
        return BeatbotDeviceData(
            device_id=device_id,
            product_id=additional.get("model") or "",
            product_category=categories[0] if categories else "",
            work_status=0,
            work_mode=0,
            error_code=0,
            battery_level=0,
            versions=[],
            is_online=True,
            is_charging=False,
        )

    async def send_command(self, device_id: str, command: str) -> None:
        """Send an action command to a device."""
        await self._request(
            "POST",
            f"{BEATBOT_API_DEVICE_ACTIONS_PATH}/{device_id}/actions",
            json_body={"action": command},
        )
