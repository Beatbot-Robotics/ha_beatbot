import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import BeatbotAPI, BeatbotAuthError, BeatbotConnectionError
from .models import BeatbotDeviceData
from iot.const import DOMAIN, NETWORK_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)


class BeatbotCoordinator(DataUpdateCoordinator[dict[str, BeatbotDeviceData]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: BeatbotAPI,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=NETWORK_REFRESH_INTERVAL),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, BeatbotDeviceData]:
        try:
            devices = await self.api.get_devices()
        except BeatbotAuthError as err:
            raise ConfigEntryAuthFailed from err
        except BeatbotConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err

        return {d.device_id: d for d in devices}
