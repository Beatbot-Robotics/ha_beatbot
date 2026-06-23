"""Tests for the Beatbot vacuum entity (battery deprecation migration)."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.components.vacuum import ATTR_BATTERY_LEVEL, VacuumEntityFeature
import pytest

from custom_components.beatbot_home.iot.category import (
    VACUUM_FEATURES_BY_CATEGORY,
)
from custom_components.beatbot_home.models import BeatbotDeviceData
from custom_components.beatbot_home.vacuum import BeatbotPoolVacuum

DEVICE_ID = "test-device-1"


def _make_coordinator(category: str) -> SimpleNamespace:
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
        is_charging=False,
    )
    return SimpleNamespace(data={DEVICE_ID: device})


@pytest.mark.parametrize(
    ("category", "expected_features"),
    [
        # "VACUUM_CLEANER" maps to POOL_CLEAN_BOT via ALEXA_CATEGORY_MAP
        ("VACUUM_CLEANER", {VacuumEntityFeature.STATE, VacuumEntityFeature.START,
                            VacuumEntityFeature.PAUSE, VacuumEntityFeature.STOP,
                            VacuumEntityFeature.RETURN_HOME}),
        # "MOWER" maps to LAWN_MOWER
        ("MOWER", {VacuumEntityFeature.STATE, VacuumEntityFeature.START,
                   VacuumEntityFeature.PAUSE, VacuumEntityFeature.STOP,
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
