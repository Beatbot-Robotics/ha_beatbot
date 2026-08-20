"""Map Beatbot `interfaceInfo` keys to fields used in change logs.

The batch state endpoint (`/devices/state/ha`) returns per-device runtime values
keyed by HA entity-shape `interfaceInfo` strings (e.g. `vacuum.state`,
`vacuum.battery`). The client library applies these values; this mapping lets
the Home Assistant coordinator log field-level changes without duplicating
the library's state mutation logic.
"""

# interfaceInfo (server-side HA capability key) -> BeatbotDeviceData field.
# `versions` has no corresponding interfaceInfo key and is not mapped here.
# `work_mode` feeds the work-mode select entity (read from `select.work_mode`
# state, set via the `select.work_mode` action).
HA_STATE_FIELD_MAP: dict[str, str] = {
    "vacuum.state": "work_status",
    "vacuum.battery": "battery_level",
    "sensor.error": "error_code",
    "select.work_mode": "work_mode",
    "switch.child_lock": "child_lock",
    "switch.voice_disturb": "voice_disturb",
}
