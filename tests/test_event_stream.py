"""Tests for the Beatbot cloud WebSocket event contract."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.beatbot.iot.event_stream import (
    BeatbotEventClient,
    _ConnectionReplaced,
    _RefreshToken,
)


def _client(hass: HomeAssistant) -> tuple[BeatbotEventClient, Mock]:
    coordinator = Mock()
    client = BeatbotEventClient(
        hass,
        SimpleNamespace(entry_id="entry"),
        SimpleNamespace(),
        SimpleNamespace(event_stream_url="ws://example/events"),
        coordinator,
    )
    return client, coordinator


def _event(
    event_id: str,
    event_type: str,
    payload: dict | None,
    device_id: str = "dev-1",
) -> str:
    return json.dumps(
        {
            "eventId": event_id,
            "type": event_type,
            "deviceId": device_id,
            "occurredAt": "2026-07-01T08:00:00Z",
            "payload": payload,
        }
    )


def test_property_event_routes_incremental_state(hass: HomeAssistant) -> None:
    client, coordinator = _client(hass)

    client._handle_text_message(
        _event(
            "event-1",
            "properties_changed",
            {"interfaceInfo": "vacuum.battery", "value": 76},
        )
    )

    coordinator.async_apply_device_event.assert_called_once_with(
        "dev-1", {"vacuum.battery": 76}
    )


def test_status_event_routes_online_state(hass: HomeAssistant) -> None:
    client, coordinator = _client(hass)

    client._handle_text_message(
        _event("event-2", "status", {"online": False})
    )

    coordinator.async_apply_device_event.assert_called_once_with(
        "dev-1", None, is_online=False
    )


def test_duplicate_event_is_applied_once(hass: HomeAssistant) -> None:
    client, coordinator = _client(hass)
    message = _event(
        "event-3",
        "properties_changed",
        {"interfaceInfo": "sensor.error", "value": 4},
    )

    client._handle_text_message(message)
    client._handle_text_message(message)

    coordinator.async_apply_device_event.assert_called_once()


def test_malformed_and_unknown_events_do_not_route(hass: HomeAssistant) -> None:
    client, coordinator = _client(hass)

    client._handle_text_message("not-json")
    client._handle_text_message(_event("event-4", "status", {"online": "yes"}))
    client._handle_text_message(_event("event-5", "future_type", {}))

    coordinator.async_apply_device_event.assert_not_called()


async def test_device_added_reloads_entry(hass: HomeAssistant) -> None:
    client, coordinator = _client(hass)
    hass.config_entries.async_reload = AsyncMock(return_value=True)

    client._handle_text_message(
        _event(
            "event-added",
            "device_added",
            {
                "deviceId": "dev-1",
                "productId": "product-1",
                "productCategory": "pool_clean_bot",
            },
        )
    )
    await hass.async_block_till_done()

    hass.config_entries.async_reload.assert_awaited_once_with("entry")
    coordinator.async_apply_device_event.assert_not_called()


async def test_device_removed_with_null_payload_reloads_entry(
    hass: HomeAssistant,
) -> None:
    client, coordinator = _client(hass)
    hass.config_entries.async_reload = AsyncMock(return_value=True)

    client._handle_text_message(
        _event("event-removed", "device_removed", None)
    )
    await hass.async_block_till_done()

    hass.config_entries.async_reload.assert_awaited_once_with("entry")
    coordinator.async_apply_device_event.assert_not_called()


async def test_malformed_device_lifecycle_events_do_not_reload(
    hass: HomeAssistant,
) -> None:
    client, _ = _client(hass)
    hass.config_entries.async_reload = AsyncMock(return_value=True)

    client._handle_text_message(
        _event("bad-added", "device_added", {"deviceId": "another-device"})
    )
    client._handle_text_message(
        _event("bad-removed", "device_removed", {})
    )
    await hass.async_block_till_done()

    hass.config_entries.async_reload.assert_not_awaited()


async def test_stop_is_idempotent(hass: HomeAssistant) -> None:
    client, _ = _client(hass)

    await client.async_stop()
    await client.async_stop()


def test_close_codes_have_distinct_policies() -> None:
    with pytest.raises(_RefreshToken):
        BeatbotEventClient._raise_for_close_code(4001, "secret", None)
    with pytest.raises(_ConnectionReplaced):
        BeatbotEventClient._raise_for_close_code(4002, "secret", None)
    with pytest.raises(ConfigEntryAuthFailed):
        BeatbotEventClient._raise_for_close_code(4003, "secret", None)
    with pytest.raises(ConnectionError):
        BeatbotEventClient._raise_for_close_code(4008, "secret", None)


async def test_rejected_token_is_refreshed_only_once(hass: HomeAssistant) -> None:
    entry = SimpleNamespace(
        entry_id="entry",
        data={"token": {"access_token": "old", "refresh_token": "refresh"}},
    )
    implementation = SimpleNamespace(
        async_refresh_token=AsyncMock(
            return_value={"access_token": "new", "refresh_token": "refresh"}
        )
    )
    oauth_session = SimpleNamespace(
        token=entry.data["token"],
        implementation=implementation,
    )
    client = BeatbotEventClient(
        hass,
        entry,
        oauth_session,
        SimpleNamespace(event_stream_url="ws://example/events"),
        Mock(),
    )
    hass.config_entries.async_update_entry = Mock(
        side_effect=lambda config_entry, data: setattr(config_entry, "data", data)
    )

    await client._async_refresh_token_once("old")
    oauth_session.token = entry.data["token"]
    await client._async_refresh_token_once("old")

    implementation.async_refresh_token.assert_awaited_once()


async def test_repeated_handshake_401_starts_reauth(hass: HomeAssistant) -> None:
    client, _ = _client(hass)
    client._handshake_refresh_attempted = True
    client._connect_and_receive = AsyncMock(
        side_effect=_RefreshToken("rejected-again", handshake=True)
    )
    client._entry.async_start_reauth = Mock()

    await client._run()

    client._entry.async_start_reauth.assert_called_once_with(hass)


async def test_reconnect_requests_full_refresh(hass: HomeAssistant) -> None:
    client, coordinator = _client(hass)
    coordinator.async_request_refresh = AsyncMock()
    client._has_connected = True

    class _WebSocket:
        closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def receive(self, *, timeout):
            raise asyncio.CancelledError

        async def close(self):
            self.closed = True

    client._oauth_session.async_ensure_token_valid = AsyncMock()
    client._oauth_session.token = {"access_token": "token"}
    websocket = _WebSocket()
    session = SimpleNamespace(ws_connect=Mock(return_value=websocket))

    with patch(
        "custom_components.beatbot.iot.event_stream.async_get_clientsession",
        return_value=session,
    ):
        with pytest.raises(asyncio.CancelledError):
            await client._connect_and_receive()

    coordinator.async_request_refresh.assert_awaited_once()
