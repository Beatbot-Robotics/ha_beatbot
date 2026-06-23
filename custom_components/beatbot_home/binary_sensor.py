from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .iot.category import ALEXA_CATEGORY_MAP, ERROR_BITS_BY_CATEGORY
from .iot.const import DOMAIN
from .coordinator import BeatbotCoordinator
from .models import BeatbotDeviceData


class BeatbotChargingSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_charging"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
        )

    @property
    def data(self) -> BeatbotDeviceData:
        return self.coordinator.data[self._device_id]

    @property
    def is_on(self) -> bool:
        return self.data.is_charging


class BeatbotOnlineSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_online"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
        )

    @property
    def data(self) -> BeatbotDeviceData:
        return self.coordinator.data[self._device_id]

    @property
    def is_on(self) -> bool:
        return self.data.is_online


class BeatbotErrorBitSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
            key: str,
            bit: int,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._bit = bit
        self._attr_unique_id = f"{device_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
        )

    @property
    def data(self) -> BeatbotDeviceData:
        return self.coordinator.data[self._device_id]

    @property
    def is_on(self) -> bool:
        return bool(self.data.error_code & self._bit)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    if data.get("coordinator") is None:
        return
    coordinator = data["coordinator"]
    entities = []
    for device_id, device_data in coordinator.data.items():
        entities.append(BeatbotChargingSensor(coordinator, device_id))
        entities.append(BeatbotOnlineSensor(coordinator, device_id))
        category = ALEXA_CATEGORY_MAP.get(device_data.product_category)
        for key, bit in ERROR_BITS_BY_CATEGORY.get(category, []):
            entities.append(BeatbotErrorBitSensor(coordinator, device_id, key, bit))
    async_add_entities(entities)
