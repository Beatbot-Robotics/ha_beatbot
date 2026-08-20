"""Tests for the Beatbot cloud event bridge."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Protocol
from unittest.mock import AsyncMock, Mock

from beatbot_cloud import (
    BeatbotAuthenticationError,
    BeatbotConnectionError,
    BeatbotEvent,
)
import pytest

from homeassistant.core import HomeAssistant

from custom_components.beatbot.iot import event_stream as event_stream_module
from custom_components.beatbot.iot.event_stream import BeatbotEventClient


class EventFactory(Protocol):
    """Create a validated Beatbot event."""

    def __call__(
        self,
        event_id: str,
        event_type: str,
        payload: dict | None,
        device_id: str = "dev-1",
    ) -> BeatbotEvent:
        """Create one event."""


@pytest.fixture(autouse=True)
def mock_client_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep event bridge tests independent from a real aiohttp session."""
    monkeypatch.setattr(
        event_stream_module,
        "async_get_clientsession",
        Mock(return_value=SimpleNamespace()),
    )


@pytest.fixture
def event_client(hass: HomeAssistant) -> tuple[BeatbotEventClient, Mock]:
    """Return an event client and its coordinator."""
    coordinator = Mock()
    entry = SimpleNamespace(entry_id="entry", data={})
    client = BeatbotEventClient(
        hass,
        entry,
        SimpleNamespace(),
        SimpleNamespace(
            event_stream_url="ws://example/events",
            async_get_access_token=AsyncMock(return_value="token"),
        ),
        coordinator,
    )
    return client, coordinator


@pytest.fixture
def event_factory() -> EventFactory:
    """Return a Beatbot event factory."""

    def _event(
        event_id: str,
        event_type: str,
        payload: dict | None,
        device_id: str = "dev-1",
    ) -> BeatbotEvent:
        return BeatbotEvent(event_id, event_type, device_id, payload)

    return _event


def test_start_registers_entry_background_task(hass: HomeAssistant) -> None:
    """The event supervisor must not block Home Assistant startup."""
    task = Mock()
    entry = SimpleNamespace(
        entry_id="entry",
        data={},
        async_create_background_task=Mock(return_value=task),
    )
    client = BeatbotEventClient(
        hass,
        entry,
        SimpleNamespace(),
        SimpleNamespace(
            event_stream_url="ws://example/events",
            async_get_access_token=AsyncMock(return_value="token"),
        ),
        Mock(),
    )

    try:
        client.async_start()
        call_args = entry.async_create_background_task.call_args.args
    finally:
        entry.async_create_background_task.call_args.args[1].close()

    entry.async_create_background_task.assert_called_once()
    assert call_args[0] is hass
    assert call_args[1].cr_code is BeatbotEventClient._run.__code__
    assert call_args[2] == "beatbot_event_stream_entry"
    assert client._task is task


def test_property_event_routes_incremental_state(
    event_client: tuple[BeatbotEventClient, Mock], event_factory: EventFactory
) -> None:
    """Route a validated property event to the compatibility overlay."""
    client, coordinator = event_client

    client._handle_event(
        event_factory(
            "event-1",
            "properties_changed",
            {"interfaceInfo": "vacuum.battery", "value": 76},
        )
    )

    coordinator.async_apply_device_event.assert_called_once_with(
        "dev-1", {"vacuum.battery": 76}
    )


def test_status_event_routes_online_state(
    event_client: tuple[BeatbotEventClient, Mock], event_factory: EventFactory
) -> None:
    """Route a validated connectivity event to the coordinator."""
    client, coordinator = event_client

    client._handle_event(event_factory("event-2", "status", {"online": False}))

    coordinator.async_apply_device_event.assert_called_once_with(
        "dev-1", None, is_online=False
    )


def test_unknown_event_does_not_route(
    event_client: tuple[BeatbotEventClient, Mock], event_factory: EventFactory
) -> None:
    """Ignore future event types returned by the library."""
    client, coordinator = event_client

    client._handle_event(event_factory("event-3", "future_type", {}))

    coordinator.async_apply_device_event.assert_not_called()


async def test_library_authentication_error_uses_optional_reauth_hook(
    hass: HomeAssistant, event_client: tuple[BeatbotEventClient, Mock]
) -> None:
    """Report terminal auth failure without requiring a reauth flow step."""
    client, _ = event_client
    client._client.async_run = AsyncMock(side_effect=BeatbotAuthenticationError)
    client._entry.async_start_reauth_if_available = Mock()

    await client._run()

    client._entry.async_start_reauth_if_available.assert_called_once_with(hass)


@pytest.mark.parametrize("event_type", ["device_added", "device_removed"])
def test_topology_event_schedules_reload(
    hass: HomeAssistant,
    event_client: tuple[BeatbotEventClient, Mock],
    event_factory: EventFactory,
    event_type: str,
) -> None:
    """Reload all entity platforms when account topology changes."""
    client, coordinator = event_client
    hass.config_entries.async_schedule_reload = Mock()
    client._remove_device_from_registries = Mock()
    payload = None if event_type == "device_removed" else {"deviceId": "dev-1"}

    client._handle_event(event_factory("event-4", event_type, payload))

    hass.config_entries.async_schedule_reload.assert_called_once_with("entry")
    coordinator.async_apply_device_event.assert_not_called()
    if event_type == "device_removed":
        client._remove_device_from_registries.assert_called_once_with("dev-1")


async def test_stop_is_idempotent(
    event_client: tuple[BeatbotEventClient, Mock],
) -> None:
    """Allow the event client to be stopped repeatedly."""
    client, _ = event_client
    client._client.async_close = AsyncMock()

    await client.async_stop()
    await client.async_stop()

    assert client._client.async_close.await_count == 2


async def test_rejected_token_is_refreshed_only_if_still_current(
    hass: HomeAssistant,
) -> None:
    """Do not rotate a token that another request has already replaced."""
    entry = SimpleNamespace(
        entry_id="entry",
        data={
            "token": {
                "access_token": "old",
                "refresh_token": "refresh",
                "expires_at": 100,
            }
        },
    )

    class OAuthSession:
        @property
        def token(self) -> dict:
            return entry.data["token"]

    oauth_session = OAuthSession()

    async def _ensure_token_valid() -> None:
        entry.data = {
            "token": {
                "access_token": "new",
                "refresh_token": "refresh",
                "expires_at": 200,
            }
        }

    oauth_session.async_ensure_token_valid = AsyncMock(side_effect=_ensure_token_valid)
    client = BeatbotEventClient(
        hass,
        entry,
        oauth_session,
        SimpleNamespace(
            event_stream_url="ws://example/events",
            async_get_access_token=AsyncMock(return_value="token"),
        ),
        Mock(),
    )
    hass.config_entries.async_update_entry = Mock(
        side_effect=lambda config_entry, data: setattr(config_entry, "data", data)
    )

    assert await client._async_refresh_token("old") == "new"
    assert await client._async_refresh_token("old") == "new"

    assert oauth_session.async_ensure_token_valid.await_count == 2
    hass.config_entries.async_update_entry.assert_called_once()


async def test_invalid_refresh_response_does_not_escape_event_callback(
    event_client: tuple[BeatbotEventClient, Mock],
) -> None:
    """Translate malformed OAuth data before it reaches the event library."""
    client, _ = event_client
    error = ValueError("invalid expires_in")
    client._oauth_session = SimpleNamespace(
        token={"access_token": "current"},
        async_ensure_token_valid=AsyncMock(side_effect=error),
    )

    with pytest.raises(BeatbotConnectionError) as exc_info:
        await client._async_refresh_token("rejected")
    assert exc_info.value.__cause__ is error


def test_library_callbacks_are_registered(
    event_client: tuple[BeatbotEventClient, Mock],
) -> None:
    """Register all Home Assistant callbacks with the client library."""
    client, coordinator = event_client

    assert client._client._event_callback == client._handle_event
    assert client._client._reconnect_callback == coordinator.async_request_refresh
    assert client._client._token_refresh_callback == client._async_refresh_token


def test_removed_device_is_detached_from_only_this_entry(
    hass: HomeAssistant,
    event_client: tuple[BeatbotEventClient, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve a registry device that is shared with another config entry."""
    client, _ = event_client
    registry_device = SimpleNamespace(id="registry-device")
    device_registry = SimpleNamespace(
        async_get_device=Mock(return_value=registry_device),
        async_update_device=Mock(),
    )
    entity_registry = SimpleNamespace(async_remove=Mock())
    monkeypatch.setattr(
        event_stream_module.dr, "async_get", Mock(return_value=device_registry)
    )
    monkeypatch.setattr(
        event_stream_module.er, "async_get", Mock(return_value=entity_registry)
    )
    monkeypatch.setattr(
        event_stream_module.er,
        "async_entries_for_device",
        Mock(
            return_value=[
                SimpleNamespace(config_entry_id="entry", entity_id="sensor.beatbot"),
                SimpleNamespace(config_entry_id="other", entity_id="sensor.shared"),
            ]
        ),
    )

    client._remove_device_from_registries("dev-1")

    device_registry.async_get_device.assert_called_once_with(
        identifiers={(event_stream_module.DOMAIN, "dev-1")}
    )
    entity_registry.async_remove.assert_called_once_with("sensor.beatbot")
    device_registry.async_update_device.assert_called_once_with(
        "registry-device", remove_config_entry_id="entry"
    )
