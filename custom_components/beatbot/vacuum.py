from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)

from .entity import BeatbotEntity
from .iot.category import (
    CATEGORY_MAP,
    ProductCategory,
    STATUS_MAP_BY_CATEGORY,
    VACUUM_FEATURES_BY_CATEGORY,
    vacuum_features_from_capabilities,
)
from .iot.const import (
    DOMAIN,
    INTERFACE_PAUSE,
    INTERFACE_RETURN_TO_BASE,
    INTERFACE_START,
)

from .coordinator import BeatbotCoordinator

VACUUM_TRANSLATION_KEYS = {
    ProductCategory.POOL_CLEAN_BOT: "beatbot_pool_vacuum",
    ProductCategory.LAWN_MOWER: "beatbot_lawn_mower_vacuum",
}


class BeatbotPoolVacuum(BeatbotEntity, StateVacuumEntity):
    def __init__(
            self,
            coordinator: BeatbotCoordinator,
            device_id: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = device_id
        category = CATEGORY_MAP.get(
            self.coordinator.data[self._device_id].product_category
        )
        if translation_key := VACUUM_TRANSLATION_KEYS.get(category):
            self._attr_translation_key = translation_key
        # Derive features from the device's advertised capabilities when the
        # backend reports them (so a model that omits e.g. vacuum.start does
        # not get a non-functional Start button). Fall back to the static
        # category map only when no capabilities are advertised at all.
        features = vacuum_features_from_capabilities(self.data.capabilities)
        if features is None:
            features = VACUUM_FEATURES_BY_CATEGORY.get(
                category, VacuumEntityFeature(0)
            )
        self._attr_supported_features = features
        self._status_map = STATUS_MAP_BY_CATEGORY.get(category, {})

    @property
    def activity(self) -> VacuumActivity:
        if self.data.error_code != 0:
            return VacuumActivity.ERROR
        return self._status_map.get(self.data.work_status, VacuumActivity.IDLE)

    @property
    def available(self) -> bool:
        return self.data.is_online and self.coordinator.last_update_success

    async def async_start(self) -> None:
        await self._async_send_command(
            self.coordinator.api.send_action(self._device_id, INTERFACE_START)
        )
        self.coordinator.async_schedule_device_state_refresh(self._device_id)

    async def async_pause(self) -> None:
        await self._async_send_command(
            self.coordinator.api.send_action(self._device_id, INTERFACE_PAUSE)
        )
        self.coordinator.async_schedule_device_state_refresh(self._device_id)

    async def async_return_to_base(self) -> None:
        await self._async_send_command(
            self.coordinator.api.send_action(
                self._device_id, INTERFACE_RETURN_TO_BASE
            )
        )
        self.coordinator.async_schedule_device_state_refresh(self._device_id)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    if data.get("coordinator") is None:
        return
    coordinator = data["coordinator"]
    async_add_entities(
        BeatbotPoolVacuum(coordinator, device_id)
        for device_id in coordinator.data
    )
