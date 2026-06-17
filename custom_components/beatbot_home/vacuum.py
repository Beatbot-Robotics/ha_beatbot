from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from iot.category import ProductCategory, VACUUM_FEATURES_BY_CATEGORY, STATUS_MAP_BY_CATEGORY
from iot.const import DOMAIN

from .coordinator import BeatbotCoordinator
from .models import BeatbotDeviceData


class BeatbotPoolVacuum(CoordinatorEntity, StateVacuumEntity):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = device_id
        category = ProductCategory(self.coordinator.data[self._device_id].product_category)
        self._attr_supported_features = VACUUM_FEATURES_BY_CATEGORY.get(category)
        self._status_map = STATUS_MAP_BY_CATEGORY.get(category, {})

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            manufacturer="Beatbot",
            model=self.data.product_id,
            sw_version=" ".join(v.version for v in self.data.versions),
        )

    @property
    def data(self) -> BeatbotDeviceData:
        return self.coordinator.data[self._device_id]

    @property
    def activity(self) -> VacuumActivity:
        if self.data.error_code != 0:
            return VacuumActivity.ERROR
        return self._status_map.get(self.data.work_status, VacuumActivity.IDLE)

    @property
    def available(self) -> bool:
        return self.data.is_online

    async def async_start(self) -> None:
        await self.coordinator.api.send_command(self._device_id, "start")

    async def async_pause(self) -> None:
        await self.coordinator.api.send_command(self._device_id, "pause")

    async def async_stop(self) -> None:
        await self.coordinator.api.send_command(self._device_id, "stop")

    async def async_return_to_base(self) -> None:
        await self.coordinator.api.send_command(self._device_id, "return_to_base")

    async def async_update(self) -> None:
        await self.coordinator.api.send_command(self._device_id, "update")


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    if data.get("coordinator") is None:
        return
    coordinator = data["coordinator"]
    async_add_entities(
        BeatbotPoolVacuum(coordinator, device_id)
        for device_id in coordinator.data
    )
