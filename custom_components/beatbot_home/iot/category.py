from enum import StrEnum

from homeassistant.components.vacuum import VacuumActivity, VacuumEntityFeature


class ProductCategory(StrEnum):
    POOL_CLEAN_BOT = "pool_clean_bot"
    LAWN_MOWER = "lawn_mower"


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
        10: VacuumActivity.CLEANING,
        11: VacuumActivity.IDLE,
        12: VacuumActivity.CLEANING,
        13: VacuumActivity.CLEANING,
        14: VacuumActivity.RETURNING,
        15: VacuumActivity.RETURNING,
        16: VacuumActivity.IDLE,
        17: VacuumActivity.CLEANING,
        18: VacuumActivity.IDLE,
        19: VacuumActivity.CLEANING,
        20: VacuumActivity.DOCKED,
    },
    ProductCategory.LAWN_MOWER: {}
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
                                    | VacuumEntityFeature.BATTERY
                                    | VacuumEntityFeature.START
                                    | VacuumEntityFeature.PAUSE
                                    | VacuumEntityFeature.STOP
                                    | VacuumEntityFeature.RETURN_HOME,
    ProductCategory.LAWN_MOWER: VacuumEntityFeature.STATE
                                | VacuumEntityFeature.BATTERY
                                | VacuumEntityFeature.START
                                | VacuumEntityFeature.PAUSE
                                | VacuumEntityFeature.STOP
                                | VacuumEntityFeature.RETURN_HOME,
}
