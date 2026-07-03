"""Tests for the Beatbot cloud WebSocket event contract."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

from homeassistant.core import HomeAssistant

from custom_components.beatbot_home.iot.event_stream import BeatbotEventClient


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
    payload: dict,
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


async def test_stop_is_idempotent(hass: HomeAssistant) -> None:
    client, _ = _client(hass)

    await client.async_stop()
    await client.async_stop()
