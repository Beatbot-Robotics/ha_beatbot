import logging
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)


@dataclass
class FirmwareVersion:
    channel: int
    version: str


@dataclass
class BeatbotDeviceData:
    device_id: str
    product_id: str
    product_category: str
    work_status: int
    work_mode: int
    error_code: int
    battery_level: int
    versions: list[FirmwareVersion]
    is_online: bool
    is_charging: bool
