from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.helpers import entity_registry as er

from .entity import BeatbotEntity
from .iot.const import DOMAIN
from .iot.category import (
    CATEGORY_MAP,
    ERROR_BITS_BY_CATEGORY,
    STATUS_DISPLAY_MAP_BY_CATEGORY,
)
from .coordinator import BeatbotCoordinator


def _remove_obsolete_firmware_entity(hass, entry) -> None:
    """Drop the registry entry for the removed BeatbotFirmwareSensor.

    Firmware now lives on the device registry (device_info.sw_version), so the
    old sensor.{device_id}_firmware entity is no longer created; evict any
    stale registry entry so users don't see a permanently-unavailable sensor.
    Matches by suffix so devices no longer in discovery are covered too.
    """
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain == "sensor" and (reg_entry.unique_id or "").endswith("_firmware"):
            registry.async_remove(reg_entry.entity_id)


class BeatbotStatusSensor(BeatbotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "work_status"

    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_status"
        category = CATEGORY_MAP.get(
            self.coordinator.data[self._device_id].product_category
        )

        self._status_map = STATUS_DISPLAY_MAP_BY_CATEGORY.get(category, {})

        self._attr_options = list(dict.fromkeys(self._status_map.values()))

    @property
    def native_value(self) -> str | None:
        return self._status_map.get(self.data.work_status)


class BeatbotBatterySensor(BeatbotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_translation_key = "battery"

    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_battery"

    @property
    def native_value(self) -> int:
        return self.data.battery_level


class BeatbotErrorSensor(BeatbotEntity, SensorEntity):
    """Decoded device error as a single readable value.

    The backend reports a bitmask via `sensor.error` (stored as
    `error_code`). This ENUM sensor decodes it to the *primary* active
    fault (lowest set bit) so a user sees "电量不足" rather than `4`. The
    full per-bit on/off breakdown is exposed as `extra_state_attributes`
    (so concurrent multi-bit faults are still inspectable). The vacuum's
    ERROR activity serves as the "any fault" binary hook.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "error"

    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
            bits: list[tuple[str, int]],
    ) -> None:
        super().__init__(coordinator, device_id)
        self._bits = bits
        self._attr_unique_id = f"{device_id}_error"
        # ENUM options must contain every value native_value can return.
        self._attr_options = [key for key, _ in bits] + ["none"]

    @property
    def native_value(self) -> str:
        for key, bit in self._bits:
            if self.data.error_code & bit:
                return key
        return "none"

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        """Per-bit on/off map. Keys are raw capability slugs (not translated)."""
        code = self.data.error_code
        return {key: bool(code & bit) for key, bit in self._bits}


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    if data.get("coordinator") is None:
        return
    coordinator = data["coordinator"]
    _remove_obsolete_firmware_entity(hass, entry)
    entities = []
    for device_id in coordinator.data:
        entities.extend([
            BeatbotStatusSensor(coordinator, device_id),
            BeatbotBatterySensor(coordinator, device_id),
        ])
        # Only expose the decoded error sensor when the device's category
        # actually has a bit map to decode against.
        category = CATEGORY_MAP.get(
            coordinator.data[device_id].product_category
        )
        if (bits := ERROR_BITS_BY_CATEGORY.get(category, [])):
            entities.append(BeatbotErrorSensor(coordinator, device_id, bits))
    # for lawn mower add
    async_add_entities(entities)
