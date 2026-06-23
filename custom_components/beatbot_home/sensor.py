from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .iot.const import DOMAIN
from .iot.category import ALEXA_CATEGORY_MAP, STATUS_MAP_BY_CATEGORY
from .coordinator import BeatbotCoordinator
from .models import BeatbotDeviceData


class BeatbotStatusSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "work_status"

    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_status"
        category = ALEXA_CATEGORY_MAP.get(
            self.coordinator.data[self._device_id].product_category
        )
        self._status_map = STATUS_MAP_BY_CATEGORY.get(category, {})
        self._attr_options = list(self._status_map.values())

    @property
    def data(self) -> BeatbotDeviceData:
        return self.coordinator.data[self._device_id]

    @property
    def native_value(self) -> str | None:
        return self._status_map.get(self.data.work_status)


class BeatbotBatterySensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_battery"

    @property
    def data(self) -> BeatbotDeviceData:
        return self.coordinator.data[self._device_id]

    @property
    def native_value(self) -> int:
        return self.data.battery_level


class BeatbotFirmwareSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_firmware"

    @property
    def data(self) -> BeatbotDeviceData:
        return self.coordinator.data[self._device_id]

    @property
    def native_value(self) -> str:
        return " ".join(v.version for v in self.data.versions)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    if data.get("coordinator") is None:
        return
    coordinator = data["coordinator"]
    entities = []
    for device_id in coordinator.data:
        entities.extend([
            BeatbotStatusSensor(coordinator, device_id),
            BeatbotBatterySensor(coordinator, device_id),
            BeatbotFirmwareSensor(coordinator, device_id),
        ])
    # for lawn mower add
    async_add_entities(entities)
