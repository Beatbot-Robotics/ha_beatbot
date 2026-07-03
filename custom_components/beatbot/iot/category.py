from enum import StrEnum

from homeassistant.components.vacuum import VacuumActivity, VacuumEntityFeature

from ..models import BeatbotCapability
from .const import (
    INTERFACE_PAUSE,
    INTERFACE_RETURN_TO_BASE,
    INTERFACE_START,
    INTERFACE_VACUUM_STATE,
)


class ProductCategory(StrEnum):
    POOL_CLEAN_BOT = "pool_clean_bot"
    LAWN_MOWER = "lawn_mower"


CATEGORY_MAP: dict[str, ProductCategory] = {
    # Backend reports productCategory in lowercase snake_case, e.g.
    # "pool_clean_bot". Uppercase aliases are kept as a fallback.
    "pool_clean_bot": ProductCategory.POOL_CLEAN_BOT,
    "POOL_CLEAN_BOT": ProductCategory.POOL_CLEAN_BOT,
    "VACUUM_CLEANER": ProductCategory.POOL_CLEAN_BOT,
    "POOL_CLEANER": ProductCategory.POOL_CLEAN_BOT,
    "lawn_mower": ProductCategory.LAWN_MOWER,
    "LAWN_MOWER": ProductCategory.LAWN_MOWER,
    "MOWER": ProductCategory.LAWN_MOWER,
}


STATUS_MAP_BY_CATEGORY: dict[ProductCategory, dict[int, VacuumActivity]] = {
    # VacuumActivity 的银蛇
    ProductCategory.POOL_CLEAN_BOT: {
        0: VacuumActivity.IDLE,
        1: VacuumActivity.RETURNING,
        2: VacuumActivity.DOCKED,
        3: VacuumActivity.DOCKED,
        4: VacuumActivity.PAUSED,
        5: VacuumActivity.CLEANING,
        6: VacuumActivity.IDLE,
        7: VacuumActivity.RETURNING,
        8: VacuumActivity.IDLE,
        9: VacuumActivity.CLEANING,
        10: VacuumActivity.IDLE,
        11: VacuumActivity.IDLE,
        12: VacuumActivity.CLEANING,
        13: VacuumActivity.CLEANING,
        14: VacuumActivity.RETURNING,
        15: VacuumActivity.RETURNING,
        16: VacuumActivity.DOCKED,
        17: VacuumActivity.CLEANING,
        18: VacuumActivity.IDLE,
        19: VacuumActivity.CLEANING,
        20: VacuumActivity.DOCKED,
    },
    ProductCategory.LAWN_MOWER: {}
}

# work_status codes that mean the device is actively charging. Charging is
# not a separate capability — it is encoded in the `vacuum.state` value
# (work_status), so the charging binary sensor is derived from these codes.
# Keep in sync with STATUS_DISPLAY_MAP_BY_CATEGORY above.
CHARGING_STATUS_CODES_BY_CATEGORY: dict[ProductCategory, set[int]] = {
    ProductCategory.POOL_CLEAN_BOT: {2},
    ProductCategory.LAWN_MOWER: set(),
}

# Sensor-facing display states: raw `work_status` code -> translation slug.
# This is deliberately separate from STATUS_MAP_BY_CATEGORY above, which
# collapses the same codes down to VacuumActivity for the vacuum entity's
# `activity`. Keeping a 1:1 code->slug map here preserves the full status
# granularity for the status sensor — every value the sensor can emit has a
# matching `entity.sensor.work_status.state` key in translations/*.json, so
# states render localized instead of as raw English VacuumActivity strings.
# Slugs MUST stay in sync with the translation files.
STATUS_DISPLAY_MAP_BY_CATEGORY: dict[ProductCategory, dict[int, str]] = {
    ProductCategory.POOL_CLEAN_BOT: {
        0: "standby",
        1: "goto_charge",
        2: "charging",
        3: "charge_done",
        4: "paused",
        5: "cleaning",
        6: "sleep",
        7: "return_trip",
        8: "clean_done",
        9: "remote_control",
        10: "clean_wait",
        11: "wifi_connect",
        12: "diving",
        13: "emerge",
        14: "auto_dock",
        15: "finish_connect",
        16: "dock",
        17: "self_cleaning",
        18: "replenish_energy",
        19: "chase_light",
        20: "dock_done",
    },
    ProductCategory.LAWN_MOWER: {},
}

ERROR_BITS_BY_CATEGORY: dict[ProductCategory, list[tuple[str, int]]] = {
    ProductCategory.POOL_CLEAN_BOT: [
        ("dust_box_full", 1 << 0),
        ("dust_box_loss", 1 << 1),
        ("power_low", 1 << 2),
        ("power_cutting", 1 << 3),
        ("env_high_temperature", 1 << 4),
        ("env_low_temperature", 1 << 5),
        ("motor_error", 1 << 6),
        ("motor_wheel_left", 1 << 7),
        ("motor_wheel_right", 1 << 8),
        ("motor_thruster_left", 1 << 9),
        ("motor_thruster_right", 1 << 10),
        ("motor_pump", 1 << 11),
        ("motor_airpump_left", 1 << 12),
        ("motor_airpump_right", 1 << 13),
        ("motor_brush", 1 << 14),
        ("motor_reagent", 1 << 15),
        ("motor_rod", 1 << 16),
        ("enter_shawdow_water_error", 1 << 17),
        ("trapped", 1 << 18),
        ("charge_high_temperature", 1 << 19),
        ("charge_low_temperature", 1 << 20),
        ("motor_thruster", 1 << 21),
        ("platform_clean_err", 1 << 22),
    ],
    ProductCategory.LAWN_MOWER: [

    ]
}

VACUUM_FEATURES_BY_CATEGORY: dict[ProductCategory, VacuumEntityFeature] = {
    ProductCategory.POOL_CLEAN_BOT: VacuumEntityFeature.STATE
                                    | VacuumEntityFeature.START
                                    | VacuumEntityFeature.PAUSE
                                    | VacuumEntityFeature.RETURN_HOME,
    ProductCategory.LAWN_MOWER: VacuumEntityFeature.STATE
                                | VacuumEntityFeature.START
                                | VacuumEntityFeature.PAUSE
                                | VacuumEntityFeature.RETURN_HOME,
}


def vacuum_features_from_capabilities(
    capabilities: dict[str, BeatbotCapability],
) -> VacuumEntityFeature | None:
    """Derive vacuum features from the device's advertised capabilities.

    Returns the derived feature set, or `None` when the device advertises no
    vacuum.* capability at all — in that case the caller should fall back to
    `VACUUM_FEATURES_BY_CATEGORY` (old firmware / backend that omits the
    capabilities array, or a device whose capabilities array carries only
    non-vacuum entries like select.work_mode / sensor.error).

    Field semantics (per HaCapabilityDTO / discovery samples):
    - `vacuum.state` with `retrievable=True` -> STATE (activity is reported).
    - `vacuum.start` / `vacuum.pause` / `vacuum.return_to_base` present and
      `non_controllable=False` -> START / PAUSE / RETURN_HOME. A capability
      flagged `non_controllable=True` is read-only and not advertised as an
      action.
    """
    if not capabilities:
        return None

    # A non-empty capabilities array that carries no vacuum.* entry means the
    # device has no vacuum surface to expose — return None so the caller falls
    # back to the category feature map instead of getting an inert
    # supported_features=0 entity.
    vacuum_capability_keys = {
        INTERFACE_VACUUM_STATE,
        INTERFACE_START,
        INTERFACE_PAUSE,
        INTERFACE_RETURN_TO_BASE,
    }
    if not (vacuum_capability_keys & capabilities.keys()):
        return None

    features = VacuumEntityFeature(0)
    state = capabilities.get(INTERFACE_VACUUM_STATE)
    if state is not None and state.retrievable:
        features |= VacuumEntityFeature.STATE
    start = capabilities.get(INTERFACE_START)
    if start is not None and not start.non_controllable:
        features |= VacuumEntityFeature.START
    pause = capabilities.get(INTERFACE_PAUSE)
    if pause is not None and not pause.non_controllable:
        features |= VacuumEntityFeature.PAUSE
    return_to_base = capabilities.get(INTERFACE_RETURN_TO_BASE)
    if return_to_base is not None and not return_to_base.non_controllable:
        features |= VacuumEntityFeature.RETURN_HOME
    return features
