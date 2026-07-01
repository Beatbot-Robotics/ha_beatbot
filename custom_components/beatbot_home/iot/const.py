DOMAIN: str = 'beatbot_home'
DEFAULT_NAME: str = 'Beatbot Home'

DEFAULT_NICK_NAME: str = 'Beatbot'

BEATBOT_HOME_HTTP_API_TIMEOUT: int = 30

NETWORK_REFRESH_INTERVAL: int = 30

# Seconds to wait after a control command before fetching the single-device
# state. The device does not report the new state the instant the action is
# issued, so reading immediately can return the previous value.
POST_CONTROL_REFRESH_DELAY: int = 3

OAUTH2_CLIENT_ID: str = 'home-assistant'
OAUTH2_AUTHORIZE_URL: str = 'http://localhost:8000/oauth2/authorize'
OAUTH2_TOKEN_URL: str = 'http://host.docker.internal:8000/oauth2/token'
OAUTH2_SCOPE: str = 'device:info'

# seconds, 14 days
SPEC_STD_LIB_EFFECTIVE_TIME = 3600 * 24 * 14
# seconds, 14 days
MANUFACTURER_EFFECTIVE_TIME = 3600 * 24 * 14

SUPPORTED_PLATFORMS: list = [
    'binary_sensor',
    'select',
    'sensor',
    'vacuum',
]

SUPPORTED_PRODUCT_CATEGORIES: set[str] = {'pool_clean_bot'}

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

DEFAULT_CLOUD_SERVER: str = 'us'
CLOUD_SERVERS: dict = {
    'us': 'United States',
    'de': 'Europe',
    'cn': '中国大陆'
}

SUPPORT_CENTRAL_GATEWAY_CTRL: list = ['us']

DEFAULT_INTEGRATION_LANGUAGE: str = 'en'
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

# Registered in Beatbot OAuth 2.0 Service
# DO NOT CHANGE UNLESS YOU HAVE AN ADMINISTRATOR PERMISSION
OAUTH_REDIRECT_URL: str = 'http://homeassistant.local:8123'

# Beatbot cloud API gateway base URL (reaches the device-resource-service
# through the /device_resource/** route, which has no Signature/Authentic filters).
# This is the dev/fallback used when no region is known.
BEATBOT_API_BASE_URL: str = 'http://host.docker.internal:8000'

# DEV DEBUG TOGGLE. When True, all device-resource requests go to the local
# dev backend (BEATBOT_API_BASE_URL), ignoring the token's `region` claim.
# >>> SET TO False BEFORE SHIPPING / PRODUCTION <<< so region routing works.
DEV_MODE: bool = True

# Resource API base URL per region. The region comes from a custom `region`
# claim in the OAuth2 access_token JWT (decoded in the config flow and stored
# on the config entry). Used only for device-resource calls; the OAuth2
# authorize/token endpoints stay global. Unknown/missing region falls back to
# BEATBOT_API_BASE_URL (local dev).
REGION_API_BASE_URL: dict[str, str] = {
    'cn': 'https://cn-iot.beatbot.com',
    'na': 'https://na-iot.beatbot.com',
    'eu': 'https://eu-iot.beatbot.com',
}
BEATBOT_API_DEVICES_PATH: str = '/openapi/v1/devices'
BEATBOT_API_DEVICE_STATES_PATH: str = '/openapi/v1/devices/state'
BEATBOT_API_DEVICE_ACTIONS_PATH: str = '/openapi/v1/devices'

# interfaceInfo keys identifying the device capabilities the backend
# registers per device (state + action). Actions are issued by POSTing the
# interfaceInfo key to /{deviceId}/actions; set-type actions also carry an
# integer `value` (taken from the `select.work_mode` capability options).
INTERFACE_VACUUM_STATE: str = 'vacuum.state'
INTERFACE_VACUUM_BATTERY: str = 'vacuum.battery'
INTERFACE_WORK_MODE: str = 'select.work_mode'
INTERFACE_SENSOR_ERROR: str = 'sensor.error'
INTERFACE_RETURN_TO_BASE: str = 'vacuum.return_to_base'
INTERFACE_START: str = 'vacuum.start'
INTERFACE_PAUSE: str = 'vacuum.pause'

# Result envelope success code (ResultCode.SUCCESS on the backend)
RESULT_SUCCESS_CODE: int = 200
