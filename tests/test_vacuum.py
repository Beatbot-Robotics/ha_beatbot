"""Tests for the Beatbot vacuum entity (battery deprecation migration)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.vacuum import ATTR_BATTERY_LEVEL, VacuumEntityFeature
import pytest

from custom_components.beatbot_home.iot.category import (
    VACUUM_FEATURES_BY_CATEGORY,
)
from custom_components.beatbot_home.iot.const import (
    INTERFACE_PAUSE,
    INTERFACE_RETURN_TO_BASE,
    INTERFACE_START,
    INTERFACE_VACUUM_STATE,
)
from custom_components.beatbot_home.models import BeatbotCapability, BeatbotDeviceData
from custom_components.beatbot_home.vacuum import BeatbotPoolVacuum

DEVICE_ID = "test-device-1"


def _make_coordinator(
    category: str,
    *,
    work_mode_options: dict[int, str] | None = None,
    capabilities: dict[str, BeatbotCapability] | None = None,
) -> SimpleNamespace:
    """Build a minimal coordinator carrying a single device."""
    device = BeatbotDeviceData(
        device_id=DEVICE_ID,
        product_id="pool-bot-x",
        product_category=category,
        work_status=0,
        work_mode=0,
        error_code=0,
        battery_level=80,
        versions=[],
        is_online=True,
        work_mode_options=work_mode_options or {},
        capabilities=capabilities or {},
    )
    return SimpleNamespace(data={DEVICE_ID: device})


@pytest.mark.parametrize(
    ("category", "expected_features"),
    [
        # "VACUUM_CLEANER" maps to POOL_CLEAN_BOT via ALEXA_CATEGORY_MAP
        ("VACUUM_CLEANER", {VacuumEntityFeature.STATE, VacuumEntityFeature.START,
                            VacuumEntityFeature.PAUSE,
                            VacuumEntityFeature.RETURN_HOME}),
        # "MOWER" maps to LAWN_MOWER
        ("MOWER", {VacuumEntityFeature.STATE, VacuumEntityFeature.START,
                   VacuumEntityFeature.PAUSE,
                   VacuumEntityFeature.RETURN_HOME}),
    ],
)
def test_vacuum_no_deprecated_battery_feature(category: str, expected_features: set) -> None:
    """Vacuum must not advertise the deprecated BATTERY feature."""
    vacuum = BeatbotPoolVacuum(_make_coordinator(category), DEVICE_ID)

    assert VacuumEntityFeature.BATTERY not in vacuum.supported_features
    assert set(vacuum.supported_features) == expected_features
    # state_attributes must no longer carry battery level (triggers deprecation)
    assert ATTR_BATTERY_LEVEL not in vacuum.state_attributes


def test_category_table_has_no_battery_feature() -> None:
    """No category advertises the deprecated BATTERY feature."""
    for features in VACUUM_FEATURES_BY_CATEGORY.values():
        assert VacuumEntityFeature.BATTERY not in features


def test_vacuum_does_not_advertise_stop() -> None:
    """No device exposes vacuum.stop (the backend registers no such action)."""
    for features in VACUUM_FEATURES_BY_CATEGORY.values():
        assert VacuumEntityFeature.STOP not in features


def test_work_mode_is_not_exposed_as_vacuum_fan_speed() -> None:
    """Work mode belongs to select.work_mode, not vacuum.set_fan_speed."""
    vacuum = BeatbotPoolVacuum(
        _make_coordinator(
            "VACUUM_CLEANER",
            work_mode_options={0: "fast", 2: "custom"},
        ),
        DEVICE_ID,
    )

    assert VacuumEntityFeature.FAN_SPEED not in vacuum.supported_features


def test_vacuum_features_derived_from_capabilities() -> None:
    """Features must match the capabilities the backend actually advertises.

    A device reporting only vacuum.state (retrievable) + vacuum.start must
    advertise STATE|START and nothing else — pause/return are absent.
    """
    capabilities = {
        INTERFACE_VACUUM_STATE: BeatbotCapability(
            interface_info=INTERFACE_VACUUM_STATE, retrievable=True,
            non_controllable=True,
        ),
        INTERFACE_START: BeatbotCapability(
            interface_info=INTERFACE_START, non_controllable=False,
        ),
    }
    vacuum = BeatbotPoolVacuum(
        _make_coordinator("VACUUM_CLEANER", capabilities=capabilities),
        DEVICE_ID,
    )

    assert set(vacuum.supported_features) == {
        VacuumEntityFeature.STATE,
        VacuumEntityFeature.START,
    }
    assert VacuumEntityFeature.PAUSE not in vacuum.supported_features
    assert VacuumEntityFeature.RETURN_HOME not in vacuum.supported_features


def test_vacuum_features_omit_missing_action() -> None:
    """No vacuum.start capability -> START must not be advertised."""
    capabilities = {
        INTERFACE_VACUUM_STATE: BeatbotCapability(
            interface_info=INTERFACE_VACUUM_STATE, retrievable=True,
            non_controllable=True,
        ),
        INTERFACE_PAUSE: BeatbotCapability(
            interface_info=INTERFACE_PAUSE, non_controllable=False,
        ),
        INTERFACE_RETURN_TO_BASE: BeatbotCapability(
            interface_info=INTERFACE_RETURN_TO_BASE, non_controllable=False,
        ),
    }
    vacuum = BeatbotPoolVacuum(
        _make_coordinator("VACUUM_CLEANER", capabilities=capabilities),
        DEVICE_ID,
    )

    assert VacuumEntityFeature.START not in vacuum.supported_features
    assert VacuumEntityFeature.PAUSE in vacuum.supported_features
    assert VacuumEntityFeature.RETURN_HOME in vacuum.supported_features


def test_vacuum_features_fall_back_when_no_capabilities() -> None:
    """Empty capabilities array -> fall back to the category feature map."""
    vacuum = BeatbotPoolVacuum(
        _make_coordinator("VACUUM_CLEANER", capabilities={}),
        DEVICE_ID,
    )

    assert set(vacuum.supported_features) == {
        VacuumEntityFeature.STATE,
        VacuumEntityFeature.START,
        VacuumEntityFeature.PAUSE,
        VacuumEntityFeature.RETURN_HOME,
    }


def test_vacuum_features_skip_readonly_action() -> None:
    """An action flagged non_controllable=True is read-only, not advertised."""
    capabilities = {
        INTERFACE_VACUUM_STATE: BeatbotCapability(
            interface_info=INTERFACE_VACUUM_STATE, retrievable=True,
            non_controllable=True,
        ),
        # Present but read-only: must NOT become a Start button.
        INTERFACE_START: BeatbotCapability(
            interface_info=INTERFACE_START, non_controllable=True,
        ),
    }
    vacuum = BeatbotPoolVacuum(
        _make_coordinator("VACUUM_CLEANER", capabilities=capabilities),
        DEVICE_ID,
    )

    assert set(vacuum.supported_features) == {VacuumEntityFeature.STATE}
    assert VacuumEntityFeature.START not in vacuum.supported_features


async def test_vacuum_action_triggers_single_device_refresh() -> None:
    """A control command must refresh only the controlled device's state,
    not run the full discovery + batch-state refresh.
    """
    coordinator = _make_coordinator("VACUUM_CLEANER")
    coordinator.api = SimpleNamespace(
        send_action=AsyncMock(),
    )
    coordinator.async_schedule_device_state_refresh = MagicMock()
    vacuum = BeatbotPoolVacuum(coordinator, DEVICE_ID)

    await vacuum.async_start()

    coordinator.api.send_action.assert_awaited_once_with(DEVICE_ID, INTERFACE_START)
    coordinator.async_schedule_device_state_refresh.assert_called_once_with(DEVICE_ID)
