"""Switch entities for Beatbot."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity

from .coordinator import BeatbotCoordinator
from .entity import BeatbotEntity
from .iot.const import (
    DOMAIN,
    INTERFACE_CHILD_LOCK,
    INTERFACE_VOICE_DISTURB,
)


@dataclass(frozen=True)
class BeatbotSwitchDescription:
    interface_info: str
    data_field: str
    translation_key: str


SWITCH_DESCRIPTIONS = (
    BeatbotSwitchDescription(
        INTERFACE_CHILD_LOCK, "child_lock", "child_lock"
    ),
    BeatbotSwitchDescription(
        INTERFACE_VOICE_DISTURB, "voice_disturb", "voice_disturb"
    ),
)


class BeatbotSwitch(BeatbotEntity, SwitchEntity):
    """A boolean switch advertised by the device capability list."""

    def __init__(
        self,
        coordinator: BeatbotCoordinator,
        device_id: str,
        description: BeatbotSwitchDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._description = description
        self._attr_unique_id = f"{device_id}_{description.data_field}"
        self._attr_translation_key = description.translation_key

    @property
    def available(self) -> bool:
        return self.data.is_online and self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        value = getattr(self.data, self._description.data_field)
        return value is True or value == 1 or value == "on"

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set_enabled('on')

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set_enabled('off')

    async def _async_set_enabled(self, enabled: str) -> None:
        await self._async_send_command(
            self.coordinator.api.set_switch(
                self._device_id,
                self._description.interface_info,
                enabled,
            )
        )
        self.coordinator.async_schedule_device_state_refresh(self._device_id)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    if data.get("coordinator") is None:
        return
    coordinator = data["coordinator"]
    entities = []
    for device_id, device in coordinator.data.items():
        for description in SWITCH_DESCRIPTIONS:
            capability = device.capabilities.get(description.interface_info)
            if capability is not None and not capability.non_controllable:
                entities.append(
                    BeatbotSwitch(coordinator, device_id, description)
                )
    async_add_entities(entities)
