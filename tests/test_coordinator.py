"""Tests for the Beatbot coordinator (productId allow-list gating)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.beatbot.api import BeatbotAuthError, BeatbotConnectionError
from custom_components.beatbot.coordinator import BeatbotCoordinator
from custom_components.beatbot.models import BeatbotDeviceData

SUPPORTED_PRODUCT = "sblekiy3t188s9ql"


def _entry() -> SimpleNamespace:
    return SimpleNamespace(entry_id="entry", async_on_unload=Mock())


def _device(device_id: str, product_id: str) -> BeatbotDeviceData:
    return BeatbotDeviceData(
        device_id=device_id,
        product_id=product_id,
        product_category="pool_clean_bot",
        work_status=0,
        work_mode=0,
        error_code=0,
        battery_level=80,
        versions=[],
        is_online=True,
    )


async def test_coordinator_only_keeps_supported_products(hass: HomeAssistant) -> None:
    """Devices whose productId is not on the allow-list are dropped."""
    supported = _device("dev-supported", SUPPORTED_PRODUCT)
    unsupported = _device("dev-unsupported", "other-product-id")
    api = SimpleNamespace(
        get_devices=AsyncMock(return_value=[supported, unsupported]),
        get_device_states=AsyncMock(return_value={}),
    )
    coordinator = BeatbotCoordinator(hass, api)

    data = await coordinator._async_update_data()

    assert "dev-supported" in data
    assert "dev-unsupported" not in data
    # Batch state endpoint still runs; unsupported device's state is simply ignored.
    api.get_device_states.assert_awaited_once()


async def test_coordinator_auth_failure_requests_reauth(
    hass: HomeAssistant,
) -> None:
    """Auth failures during first refresh become ConfigEntryAuthFailed."""
    api = SimpleNamespace(
        get_devices=AsyncMock(side_effect=BeatbotAuthError),
        get_device_states=AsyncMock(return_value={}),
    )
    coordinator = BeatbotCoordinator(hass, api)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_coordinator_connection_failure_is_retryable(
    hass: HomeAssistant,
) -> None:
    """Connection failures during first refresh remain retryable setup failures."""
    api = SimpleNamespace(
        get_devices=AsyncMock(side_effect=BeatbotConnectionError),
        get_device_states=AsyncMock(return_value={}),
    )
    coordinator = BeatbotCoordinator(hass, api)

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_coordinator_empty_allow_list_drops_everything(
    hass: HomeAssistant, monkeypatch
) -> None:
    """With an empty allow-list no device is retained."""
    from custom_components.beatbot import coordinator as coord_mod

    monkeypatch.setattr(coord_mod, "SUPPORTED_PRODUCT_IDS", set())
    supported = _device("dev-supported", SUPPORTED_PRODUCT)
    api = SimpleNamespace(
        get_devices=AsyncMock(return_value=[supported]),
        get_device_states=AsyncMock(return_value={}),
    )
    coordinator = BeatbotCoordinator(hass, api)

    data = await coordinator._async_update_data()

    assert data == {}


async def test_device_event_overlays_state_without_resetting_poll(
    hass: HomeAssistant,
    caplog,
) -> None:
    """A push updates the existing device and only notifies listeners."""
    coordinator = BeatbotCoordinator(hass, SimpleNamespace())
    device = _device("dev-1", SUPPORTED_PRODUCT)
    coordinator.async_set_updated_data({"dev-1": device})
    listener = Mock()
    remove_listener = coordinator.async_add_listener(listener)
    next_poll = coordinator._unsub_refresh
    coordinator.last_update_success = False

    with caplog.at_level(logging.INFO, logger="custom_components.beatbot.coordinator"):
        coordinator.async_apply_device_event(
            "dev-1", {"vacuum.battery": 42}, is_online=False
        )

    assert device.battery_level == 42
    assert device.is_online is False
    assert "source=websocket" in caplog.text
    assert "interfaceInfo=vacuum.battery, old=80, new=42" in caplog.text
    assert "interfaceInfo=online, old=True, new=False" in caplog.text
    assert coordinator.last_update_success
    assert coordinator._unsub_refresh is next_poll
    listener.assert_called_once()
    remove_listener()


async def test_device_event_ignores_unknown_device(hass: HomeAssistant) -> None:
    coordinator = BeatbotCoordinator(hass, SimpleNamespace())
    coordinator.async_set_updated_data({})

    coordinator.async_apply_device_event(
        "unknown", {"vacuum.battery": 42}, is_online=False
    )

    assert coordinator.data == {}


async def test_post_control_refresh_fetches_only_target_device(
    hass: HomeAssistant, monkeypatch, caplog
) -> None:
    """A delayed fallback GET applies state for the controlled device."""
    from custom_components.beatbot import coordinator as coord_mod

    monkeypatch.setattr(coord_mod, "POST_CONTROL_REFRESH_DELAY", 0)
    device = _device("dev-1", SUPPORTED_PRODUCT)
    api = SimpleNamespace(
        get_device_state=AsyncMock(
            return_value={
                "states": {"vacuum.state": 5},
                "is_online": True,
            }
        )
    )
    coordinator = BeatbotCoordinator(hass, api)
    coordinator.async_set_updated_data({"dev-1": device})

    with caplog.at_level(logging.INFO, logger="custom_components.beatbot.coordinator"):
        coordinator.async_schedule_device_state_refresh("dev-1")
        task = coordinator._refresh_tasks["dev-1"]
        await task

    api.get_device_state.assert_awaited_once_with("dev-1")
    assert device.work_status == 5
    assert "source=post_control" in caplog.text
    assert "states={'vacuum.state': 5}" in caplog.text
    assert "interfaceInfo=vacuum.state, old=0, new=5" in caplog.text
    assert coordinator._refresh_tasks == {}


async def test_post_control_refresh_debounces_per_device(
    hass: HomeAssistant,
) -> None:
    """A later command cancels the older pending refresh for that device."""
    coordinator = BeatbotCoordinator(hass, SimpleNamespace())
    started = asyncio.Event()
    release = asyncio.Event()

    async def _refresh(_device_id: str) -> None:
        started.set()
        await release.wait()

    refresh = AsyncMock(side_effect=_refresh)
    coordinator.async_refresh_device_state = refresh

    coordinator.async_schedule_device_state_refresh("dev-1")
    first = coordinator._refresh_tasks["dev-1"]
    await started.wait()
    coordinator.async_schedule_device_state_refresh("dev-1")
    second = coordinator._refresh_tasks["dev-1"]
    release.set()
    await second
    await asyncio.gather(first, return_exceptions=True)

    assert first.cancelled()
    assert refresh.await_count == 2
    refresh.assert_awaited_with("dev-1")
    assert coordinator._refresh_tasks == {}


async def test_cancel_pending_post_control_refreshes(
    hass: HomeAssistant,
) -> None:
    """Unload cancellation prevents delayed requests from outliving the API."""
    coordinator = BeatbotCoordinator(hass, SimpleNamespace())

    coordinator.async_schedule_device_state_refresh("dev-1")
    coordinator.async_schedule_device_state_refresh("dev-2")
    tasks = list(coordinator._refresh_tasks.values())

    coordinator.async_cancel_pending_refreshes()
    await asyncio.gather(*tasks, return_exceptions=True)

    assert all(task.cancelled() for task in tasks)
    assert coordinator._refresh_tasks == {}


async def test_poll_keeps_device_until_three_successful_discovery_misses(
    hass: HomeAssistant,
) -> None:
    device = _device("dev-1", SUPPORTED_PRODUCT)
    api = SimpleNamespace(
        get_devices=AsyncMock(return_value=[]),
        get_device_states=AsyncMock(return_value={}),
    )
    coordinator = BeatbotCoordinator(hass, api, _entry())
    coordinator.async_set_updated_data({"dev-1": device})
    coordinator._remove_device_from_registries = Mock()
    coordinator._schedule_entry_reload = Mock()

    first = await coordinator._async_update_data()
    second = await coordinator._async_update_data()

    assert first == {"dev-1": device}
    assert second == {"dev-1": device}
    coordinator._remove_device_from_registries.assert_not_called()
    coordinator._schedule_entry_reload.assert_not_called()

    third = await coordinator._async_update_data()

    assert third == {"dev-1": device}
    coordinator._remove_device_from_registries.assert_called_once_with("dev-1")
    coordinator._schedule_entry_reload.assert_called_once()


async def test_poll_missing_counter_resets_when_device_returns(
    hass: HomeAssistant,
) -> None:
    device = _device("dev-1", SUPPORTED_PRODUCT)
    api = SimpleNamespace(
        get_devices=AsyncMock(side_effect=[[], [device], [], []]),
        get_device_states=AsyncMock(return_value={}),
    )
    coordinator = BeatbotCoordinator(hass, api, _entry())
    coordinator.async_set_updated_data({"dev-1": device})
    coordinator._remove_device_from_registries = Mock()
    coordinator._schedule_entry_reload = Mock()

    for _ in range(4):
        await coordinator._async_update_data()

    coordinator._remove_device_from_registries.assert_not_called()
    coordinator._schedule_entry_reload.assert_not_called()


async def test_poll_new_device_schedules_platform_reload(
    hass: HomeAssistant,
) -> None:
    device = _device("dev-new", SUPPORTED_PRODUCT)
    api = SimpleNamespace(
        get_devices=AsyncMock(return_value=[device]),
        get_device_states=AsyncMock(return_value={}),
    )
    coordinator = BeatbotCoordinator(hass, api, _entry())
    coordinator.async_set_updated_data({})
    coordinator._schedule_entry_reload = Mock()

    data = await coordinator._async_update_data()

    assert data == {"dev-new": device}
    coordinator._schedule_entry_reload.assert_called_once()


async def test_initial_poll_does_not_reload_discovered_devices(
    hass: HomeAssistant,
) -> None:
    """Do not reload platforms for devices found during initial setup."""
    device = _device("dev-new", SUPPORTED_PRODUCT)
    api = SimpleNamespace(
        get_devices=AsyncMock(return_value=[device]),
        get_device_states=AsyncMock(return_value={}),
    )
    coordinator = BeatbotCoordinator(hass, api, _entry())
    coordinator._registered_device_ids = Mock(return_value=set())
    coordinator._schedule_entry_reload = Mock()

    data = await coordinator._async_update_data()

    assert data == {"dev-new": device}
    coordinator._schedule_entry_reload.assert_not_called()


async def test_poll_preserves_state_missing_from_batch(
    hass: HomeAssistant,
) -> None:
    """Keep runtime values when discovery returns no state for a device."""
    previous = _device("dev-1", SUPPORTED_PRODUCT)
    previous.work_status = 5
    previous.work_mode = 2
    previous.error_code = 4
    previous.battery_level = 42
    previous.is_online = False
    previous.child_lock = True
    previous.voice_disturb = True
    discovered = _device("dev-1", SUPPORTED_PRODUCT)
    discovered.name = "Updated name"
    api = SimpleNamespace(
        get_devices=AsyncMock(return_value=[discovered]),
        get_device_states=AsyncMock(return_value={}),
    )
    coordinator = BeatbotCoordinator(hass, api, _entry())
    coordinator.async_set_updated_data({"dev-1": previous})

    data = await coordinator._async_update_data()

    assert data["dev-1"].name == "Updated name"
    assert data["dev-1"].work_status == 5
    assert data["dev-1"].work_mode == 2
    assert data["dev-1"].error_code == 4
    assert data["dev-1"].battery_level == 42
    assert data["dev-1"].is_online is False
    assert data["dev-1"].child_lock is True
    assert data["dev-1"].voice_disturb is True


async def test_poll_preserves_state_when_batch_request_fails(
    hass: HomeAssistant,
) -> None:
    """Keep last-known values during a best-effort state request failure."""
    previous = _device("dev-1", SUPPORTED_PRODUCT)
    previous.battery_level = 42
    previous.work_status = 5
    discovered = _device("dev-1", SUPPORTED_PRODUCT)
    api = SimpleNamespace(
        get_devices=AsyncMock(return_value=[discovered]),
        get_device_states=AsyncMock(side_effect=BeatbotConnectionError("offline")),
    )
    coordinator = BeatbotCoordinator(hass, api, _entry())
    coordinator.async_set_updated_data({"dev-1": previous})

    data = await coordinator._async_update_data()

    assert data["dev-1"].battery_level == 42
    assert data["dev-1"].work_status == 5


async def test_poll_overlays_partial_state_on_previous_values(
    hass: HomeAssistant,
) -> None:
    """Update only fields present in a partial batch response."""
    previous = _device("dev-1", SUPPORTED_PRODUCT)
    previous.work_status = 5
    previous.battery_level = 42
    discovered = _device("dev-1", SUPPORTED_PRODUCT)
    api = SimpleNamespace(
        get_devices=AsyncMock(return_value=[discovered]),
        get_device_states=AsyncMock(
            return_value={"dev-1": {"states": {"vacuum.battery": 75}}}
        ),
    )
    coordinator = BeatbotCoordinator(hass, api, _entry())
    coordinator.async_set_updated_data({"dev-1": previous})

    data = await coordinator._async_update_data()

    assert data["dev-1"].work_status == 5
    assert data["dev-1"].battery_level == 75


async def test_poll_removes_registry_only_stale_device_after_three_misses(
    hass: HomeAssistant,
) -> None:
    api = SimpleNamespace(
        get_devices=AsyncMock(return_value=[]),
        get_device_states=AsyncMock(return_value={}),
    )
    coordinator = BeatbotCoordinator(hass, api, _entry())
    coordinator.async_set_updated_data({})
    coordinator._registered_device_ids = Mock(return_value={"dev-stale"})
    coordinator._remove_device_from_registries = Mock()
    coordinator._schedule_entry_reload = Mock()

    await coordinator._async_update_data()
    await coordinator._async_update_data()
    coordinator._remove_device_from_registries.assert_not_called()

    await coordinator._async_update_data()

    coordinator._remove_device_from_registries.assert_called_once_with("dev-stale")
    coordinator._schedule_entry_reload.assert_called_once()


def test_registry_removal_detaches_only_this_config_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve a device shared by another config entry."""
    from custom_components.beatbot import coordinator as coord_mod

    registry_device = SimpleNamespace(
        id="registry-device",
        identifiers={(coord_mod.DOMAIN, "dev-1"), ("other", "shared")},
    )
    device_registry = SimpleNamespace(
        async_get_device=Mock(return_value=registry_device),
        async_update_device=Mock(),
    )
    entity_registry = SimpleNamespace(async_remove=Mock())
    monkeypatch.setattr(coord_mod.dr, "async_get", Mock(return_value=device_registry))
    monkeypatch.setattr(coord_mod.er, "async_get", Mock(return_value=entity_registry))
    monkeypatch.setattr(
        coord_mod.er,
        "async_entries_for_device",
        Mock(
            return_value=[
                SimpleNamespace(config_entry_id="entry", entity_id="sensor.beatbot"),
                SimpleNamespace(config_entry_id="other", entity_id="sensor.shared"),
            ]
        ),
    )
    coordinator = BeatbotCoordinator(hass, SimpleNamespace(), _entry())

    coordinator._remove_device_from_registries("dev-1")

    device_registry.async_get_device.assert_called_once_with(
        identifiers={(coord_mod.DOMAIN, "dev-1")}
    )
    entity_registry.async_remove.assert_called_once_with("sensor.beatbot")
    device_registry.async_update_device.assert_called_once_with(
        "registry-device", remove_config_entry_id="entry"
    )


def test_entry_reload_is_scheduled_once(hass: HomeAssistant) -> None:
    """Use Home Assistant's scheduler and coalesce topology reloads."""
    hass.config_entries.async_schedule_reload = Mock()
    coordinator = BeatbotCoordinator(hass, SimpleNamespace(), _entry())

    coordinator._schedule_entry_reload()
    coordinator._schedule_entry_reload()

    hass.config_entries.async_schedule_reload.assert_called_once_with("entry")
