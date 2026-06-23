DOMAIN: str = 'beatbot_home'
DEFAULT_NAME: str = 'Beatbot Home'

DEFAULT_NICK_NAME: str = 'Beatbot'

BEATBOT_HOME_HTTP_API_TIMEOUT: int = 30

NETWORK_REFRESH_INTERVAL: int = 30

OAUTH2_CLIENT_ID: str = 'home-assistant'
OAUTH2_AUTHORIZE_URL: str = 'http://localhost:8000/oauth2/authorize'
OAUTH2_TOKEN_URL: str = 'http://host.docker.internal:8000/oauth2/token'
OAUTH2_SCOPE: str = 'device:info'

# seconds, 14 days
SPEC_STD_LIB_EFFECTIVE_TIME = 3600*24*14
# seconds, 14 days
MANUFACTURER_EFFECTIVE_TIME = 3600*24*14

SUPPORTED_PLATFORMS: list = [
    'binary_sensor',
    'button',
    'device_tracker',
    'select',
    'sensor',
    'switch',
    'vacuum',
]

UNSUPPORTED_MODELS: list = [
    'chuangmi.ir.v2',
    'era.airp.cwb03',
    'hmpace.motion.v6nfc',
    'k0918.toothbrush.t700'
]

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
# through the /device_resource/** route, which has no Signature/Authentic filters)
BEATBOT_API_BASE_URL: str = 'http://host.docker.internal:8000'
BEATBOT_API_DEVICES_PATH: str = '/device_resource/api/v1/devices'
BEATBOT_API_DEVICE_STATE_PATH: str = '/device_resource/api/v1/devices/state'
BEATBOT_API_DEVICE_ACTIONS_PATH: str = '/device_resource/api/v1/devices'
BEATBOT_API_PLATFORM: str = 'homeassistant'

# Result envelope success code (ResultCode.SUCCESS on the backend)
RESULT_SUCCESS_CODE: int = 200
