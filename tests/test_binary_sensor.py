"""Tests for Beatbot binary_sensor entities (charging indicator)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.beatbot_home.binary_sensor import BeatbotChargingSensor
from custom_components.beatbot_home.iot.category import (
    CATEGORY_MAP,
    CHARGING_STATUS_CODES_BY_CATEGORY,
)
from custom_components.beatbot_home.models import BeatbotDeviceData

DEVICE_ID = "test-device-1"
POOL_CODES = CHARGING_STATUS_CODES_BY_CATEGORY[
    CATEGORY_MAP["pool_clean_bot"]
]


def _make_coordinator(work_status: int, *, is_online: bool = True) -> SimpleNamespace:
    device = BeatbotDeviceData(
        device_id=DEVICE_ID,
        product_id="pool-bot-x",
        product_category="pool_clean_bot",
        work_status=work_status,
        work_mode=0,
        error_code=0,
        battery_level=80,
        versions=[],
        is_online=is_online,
    )
    return SimpleNamespace(data={DEVICE_ID: device})


@pytest.mark.parametrize(
    ("work_status", "expected"),
    [
        (2, True),   # charging
        (3, False),  # charge_done — not actively charging
        (5, False),  # cleaning
        (0, False),  # standby
    ],
)
def test_charging_sensor_reflects_work_status(work_status: int, expected: bool) -> None:
    """is_on is True only when work_status is a charging code."""
    sensor = BeatbotChargingSensor(
        _make_coordinator(work_status), DEVICE_ID, POOL_CODES
    )

    assert sensor.is_on is expected


def test_charging_sensor_offline_unavailable() -> None:
    """An offline device reports unavailable, not a stale charging state."""
    sensor = BeatbotChargingSensor(
        _make_coordinator(2, is_online=False), DEVICE_ID, POOL_CODES
    )

    assert sensor.available is False
