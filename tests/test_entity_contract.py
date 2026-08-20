"""Regression tests for the public Beatbot entity contract."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.beatbot.binary_sensor import (
    BeatbotChargingSensor,
    BeatbotOnlineSensor,
)
from custom_components.beatbot.iot.category import (
    CATEGORY_MAP,
    CHARGING_STATUS_CODES_BY_CATEGORY,
    ERROR_BITS_BY_CATEGORY,
)
from custom_components.beatbot.iot.const import (
    INTERFACE_START,
    SUPPORTED_PLATFORMS,
)
from custom_components.beatbot.models import BeatbotDeviceData
from custom_components.beatbot.select import BeatbotWorkModeSelect
from custom_components.beatbot.sensor import (
    BeatbotBatterySensor,
    BeatbotErrorSensor,
    BeatbotStatusSensor,
)
from custom_components.beatbot.switch import BeatbotSwitch, SWITCH_DESCRIPTIONS
from custom_components.beatbot.vacuum import BeatbotPoolVacuum

DEVICE_ID = "test-device-1"


def _coordinator(*, is_online: bool = True) -> SimpleNamespace:
    """Build a coordinator with every currently exposed entity capability."""
    device = BeatbotDeviceData(
        device_id=DEVICE_ID,
        product_id="sblekiy3t188s9ql",
        product_category="pool_clean_bot",
        work_status=2,
        work_mode=2,
        error_code=0,
        battery_level=80,
        versions=[],
        is_online=is_online,
        work_mode_options={0: "fast", 2: "custom"},
    )
    return SimpleNamespace(
        data={DEVICE_ID: device},
        last_update_success=True,
        api=SimpleNamespace(
            send_action=AsyncMock(),
            set_work_mode=AsyncMock(),
            set_switch=AsyncMock(),
        ),
        async_apply_device_event=Mock(),
        async_schedule_device_state_refresh=Mock(),
    )


def _entities(coordinator: SimpleNamespace) -> list:
    """Return one instance of every existing entity kind."""
    category = CATEGORY_MAP["pool_clean_bot"]
    return [
        BeatbotPoolVacuum(coordinator, DEVICE_ID),
        BeatbotStatusSensor(coordinator, DEVICE_ID),
        BeatbotBatterySensor(coordinator, DEVICE_ID),
        BeatbotErrorSensor(coordinator, DEVICE_ID, ERROR_BITS_BY_CATEGORY[category]),
        BeatbotOnlineSensor(coordinator, DEVICE_ID),
        BeatbotChargingSensor(
            coordinator,
            DEVICE_ID,
            CHARGING_STATUS_CODES_BY_CATEGORY[category],
        ),
        BeatbotWorkModeSelect(coordinator, DEVICE_ID),
        *(BeatbotSwitch(coordinator, DEVICE_ID, item) for item in SWITCH_DESCRIPTIONS),
    ]


def test_supported_platforms_are_unchanged() -> None:
    """Keep every custom-integration platform while Core remains sensor-only."""
    assert SUPPORTED_PLATFORMS == [
        Platform.BINARY_SENSOR,
        Platform.SELECT,
        Platform.SENSOR,
        Platform.SWITCH,
        Platform.VACUUM,
    ]


def test_entity_unique_ids_and_translation_keys_are_unchanged() -> None:
    """Prevent infrastructure updates from migrating or renaming entities."""
    entities = _entities(_coordinator())

    assert [(entity.unique_id, entity.translation_key) for entity in entities] == [
        (DEVICE_ID, "beatbot_pool_vacuum"),
        (f"{DEVICE_ID}_status", "work_status"),
        (f"{DEVICE_ID}_battery", "battery"),
        (f"{DEVICE_ID}_error", "error"),
        (f"{DEVICE_ID}_online", "online"),
        (f"{DEVICE_ID}_charging", "charging"),
        (f"{DEVICE_ID}_work_mode", "work_mode"),
        (f"{DEVICE_ID}_child_lock", "child_lock"),
        (f"{DEVICE_ID}_voice_disturb", "voice_disturb"),
    ]


def test_offline_availability_preserves_connectivity_and_diagnostics() -> None:
    """Report offline explicitly while disabling only stateful controls."""
    coordinator = _coordinator(is_online=False)
    entities = _entities(coordinator)
    (
        vacuum,
        status,
        battery,
        error,
        online,
        charging,
        work_mode,
        child_lock,
        voice_disturb,
    ) = entities

    assert online.available
    assert online.is_on is False
    assert status.available
    assert battery.available
    assert error.available
    assert not vacuum.available
    assert not charging.available
    assert not work_mode.available
    assert not child_lock.available
    assert not voice_disturb.available


def test_removed_device_is_unavailable_without_key_error() -> None:
    """Short-circuit availability when topology changes before reload."""
    coordinator = _coordinator()
    entities = _entities(coordinator)
    coordinator.data = {}

    assert all(not entity.available for entity in entities)


def test_failed_coordinator_update_marks_all_entities_unavailable() -> None:
    """Honor coordinator health independently from device connectivity."""
    coordinator = _coordinator()
    entities = _entities(coordinator)
    coordinator.last_update_success = False

    assert all(not entity.available for entity in entities)


async def test_offline_command_is_not_created() -> None:
    """Reject an offline action before constructing its API coroutine."""
    coordinator = _coordinator(is_online=False)
    vacuum = BeatbotPoolVacuum(coordinator, DEVICE_ID)

    with pytest.raises(HomeAssistantError):
        await vacuum.async_start()

    coordinator.api.send_action.assert_not_called()
    coordinator.async_schedule_device_state_refresh.assert_not_called()


async def test_online_command_is_awaited_once() -> None:
    """Keep the existing vacuum command and reconciliation behavior."""
    coordinator = _coordinator()
    vacuum = BeatbotPoolVacuum(coordinator, DEVICE_ID)

    await vacuum.async_start()

    coordinator.api.send_action.assert_awaited_once_with(DEVICE_ID, INTERFACE_START)
    coordinator.async_schedule_device_state_refresh.assert_called_once_with(DEVICE_ID)
