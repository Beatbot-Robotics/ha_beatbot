DOMAIN: str = 'beatbot'
DEFAULT_NAME: str = 'Beatbot'

DEFAULT_NICK_NAME: str = 'Beatbot'

BEATBOT_HTTP_API_TIMEOUT: int = 30

# WebSocket events provide real-time state changes. Keep a low-frequency full
# refresh for discovery and reconciliation when an event is missed.
NETWORK_REFRESH_INTERVAL: int = 10 * 60

# Seconds to wait after a control command before fetching the single-device
# state. The device does not report the new state the instant the action is
# issued, so reading immediately can return the previous value.
POST_CONTROL_REFRESH_DELAY: int = 5

OAUTH2_CLIENT_ID: str = 'home-assistant'
OAUTH2_AUTHORIZE_URL: str = 'https://oauth.beatbot.com/oauth2/authorize'
OAUTH2_TOKEN_URL: str = 'https://oauth.beatbot.com/oauth2/token'
OAUTH2_SCOPE: str = 'device:info'

# seconds, 14 days
SPEC_STD_LIB_EFFECTIVE_TIME = 3600 * 24 * 14
# seconds, 14 days
MANUFACTURER_EFFECTIVE_TIME = 3600 * 24 * 14

SUPPORTED_PLATFORMS: list = [
    'binary_sensor',
    'select',
    'sensor',
    'switch',
    'vacuum',
]

SUPPORTED_PRODUCT_CATEGORIES: set[str] = {'pool_clean_bot','clean_base_station'}

SUPPORTED_PRODUCT_IDS: set[str] = {
    'sblekiy3t188s9ql',
    'khepk01dtgj3udq0',
    'xvwp9zj6bgsmk9tv',
    '8fbwsy7h49c8hrzy',
    '0sjj9a0jwq8z3ljz',
    's34unj9n9wfo737h',
    'd0jf1j3bl6ql94g1',
    'tz8vjwgcdle3w2lj'
}


INTEGRATION_LANGUAGES = {
    'de': 'Deutsch',
    'en': 'English',
    'es': 'Español',
    'fr': 'Français',
    'it': 'Italiano',
    'pt': 'Português',
    'pt-BR': 'Português (Brasil)',
    'cs': 'Czechos',
    'zh-Hans': '简体中文',
}

DEFAULT_COVER_DEAD_ZONE_WIDTH: int = 0
MIN_COVER_DEAD_ZONE_WIDTH: int = 0
MAX_COVER_DEAD_ZONE_WIDTH: int = 5

DEFAULT_CTRL_MODE: str = 'auto'

# Resource API base URL per region. The region comes from a custom `region`
# claim in the OAuth2 access_token JWT (decoded in the config flow and stored
# on the config entry). Used only for device-resource calls; the OAuth2
# authorize/token endpoints stay global. An unknown or missing region is
# rejected at config-flow time — there is no fallback region.
REGION_API_BASE_URL: dict[str, str] = {
    'cn': 'https://cn-iot.beatbot.com',
    'na': 'https://na-iot.beatbot.com',
    'eu': 'https://eu-iot.beatbot.com',
}
BEATBOT_API_DEVICES_PATH: str = '/openapi/v1/ha'
BEATBOT_API_DEVICE_STATES_PATH: str = '/openapi/v1/ha/state'
BEATBOT_API_DEVICE_ACTIONS_PATH: str = '/openapi/v1/ha'

# Account-scoped Home Assistant event stream. The server authenticates the
# WebSocket upgrade with the same OAuth bearer token used by the REST API.
BEATBOT_API_EVENTS_PATH: str = '/openapi/v1/ha/ws'
EVENT_RECONNECT_MIN_DELAY: float = 1.0
EVENT_RECONNECT_MAX_DELAY: float = 60.0
EVENT_RECONNECT_MAX_ATTEMPTS: int = 10
EVENT_PROBE_INTERVAL: float = 300.0
EVENT_HEARTBEAT_INTERVAL: float = 30.0
EVENT_HEARTBEAT_TIMEOUT: float = 90.0
EVENT_DEDUP_CACHE_SIZE: int = 1024

# interfaceInfo keys identifying the device capabilities the backend
# registers per device (state + action). Actions are issued by POSTing the
# interfaceInfo key to /{deviceId}/actions; set-type actions also carry an
# integer `value` (taken from the `select.work_mode` capability options).
INTERFACE_VACUUM_STATE: str = 'vacuum.state'
INTERFACE_VACUUM_BATTERY: str = 'vacuum.battery'
INTERFACE_WORK_MODE: str = 'select.work_mode'
INTERFACE_SENSOR_ERROR: str = 'sensor.error'
INTERFACE_CHILD_LOCK: str = 'switch.child_lock'
INTERFACE_VOICE_DISTURB: str = 'switch.voice_disturb'
INTERFACE_RETURN_TO_BASE: str = 'vacuum.return_to_base'
INTERFACE_START: str = 'vacuum.start'
INTERFACE_PAUSE: str = 'vacuum.pause'

# Result envelope success code (ResultCode.SUCCESS on the backend)
RESULT_SUCCESS_CODE: int = 200
