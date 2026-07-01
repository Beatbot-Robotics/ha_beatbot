"""Shared base entity for all Beatbot platforms.

Every entity attached to a device contributes the same `device_info`
(name / manufacturer / model / sw_version) to the device registry, instead
of relying on a single entity (the vacuum) to supply it. That way the
device is populated correctly no matter which platform's entities load
first or fail to load.
"""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import BeatbotCoordinator
from .iot.const import DOMAIN
from .models import BeatbotDeviceData


class BeatbotEntity(CoordinatorEntity):
    """Common base: device metadata + per-device data accessor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BeatbotCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def data(self) -> BeatbotDeviceData:
        return self.coordinator.data[self._device_id]

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self.data.name or None,
            manufacturer="Beatbot",
            model=self.data.model or self.data.product_id,
            # Show each firmware channel's version distinctly (e.g.
            # "ch1:0.0.80 ch2:0.0.80") rather than collapsing to one value.
            sw_version=" ".join(
                f"ch{v.channel}:{v.version}"
                for v in self.data.versions
                if v.version
            ) or None,
        )
