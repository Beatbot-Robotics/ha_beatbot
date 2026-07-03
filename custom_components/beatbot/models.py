import logging
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)


@dataclass
class FirmwareVersion:
    channel: int
    version: str


@dataclass
class BeatbotCapability:
    """A single HA capability advertised by the backend discovery.

    Mirrors `HaCapabilityDTO`: `non_controllable=True` means read-only (the
    property exists but cannot be set), `retrievable=True` means the value can
    be read back.
    """

    interface_info: str
    retrievable: bool = False
    proactively_reported: bool = False
    non_controllable: bool = False


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
    child_lock: bool = False
    voice_disturb: bool = False
    name: str = ""
    model: str = ""
    # Per-device work-mode map parsed from the `select.work_mode` capability
    # `configuration` (value -> label). Drives the work-mode select entity.
    work_mode_options: dict[int, str] = field(default_factory=dict)
    # Per-device capabilities keyed by `interfaceInfo` (e.g. "vacuum.start").
    # Drives dynamic vacuum feature derivation; empty when the discovery
    # payload carries no capabilities (caller falls back to category map).
    capabilities: dict[str, BeatbotCapability] = field(default_factory=dict)
