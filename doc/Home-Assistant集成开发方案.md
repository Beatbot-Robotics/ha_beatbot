# Home Assistant 集成开发方案

> 基于 beatbot-cloud 现有架构（Alexa / Google Home 集成经验），开发泳池机器人 Home Assistant 集成。

---

## 一、整体架构

### 1.1 系统交互链路

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Home Assistant 侧（Python）                   │
│                                                                      │
│  用户添加集成 → config_flow.py（OAuth2 授权码流程）                    │
│       ↓                                                              │
│  __init__.py::async_setup_entry()                                    │
│       ↓                                                              │
│  coordinator.py（DataUpdateCoordinator，30s 轮询）                    │
│       ↓                                                              │
│  vacuum.py / sensor.py / button.py / select.py                      │
│  （StateVacuumEntity + 辅助 Entity）                                  │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ HTTPS（Bearer Token）
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│                        beatbot-cloud 侧（Java）                       │
│                                                                      │
│  Gateway（/oauth2/** → oauth-server）                                 │
│  Gateway（/device_resource/** → device-resource-service）             │
│       ↓                                                              │
│  device-resource-service                                             │
│    ├─ DeviceResourceController（复用，新增 platform=homeassistant）    │
│    ├─ DeviceServiceImpl（新增 HA 命令翻译逻辑）                       │
│    └─ Kafka Receivers（PropertyChangeReceiver / DeviceStatusReceiver │
│       新增 HA 推送通道）                                              │
│       ↓                                                              │
│  app-device（InternalDeviceService 调用）                             │
│    ├─ POST /api/command/property/write                               │
│    └─ POST /api/command/property/read                                │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 IoT Class

| 阶段 | iot_class | 说明 |
|------|-----------|------|
| Phase 1 | `cloud_polling` | 30s 轮询设备状态 |
| Phase 2（可选） | `cloud_push` | 云端 WebSocket/SSE 推送状态变更 |

### 1.3 Integration Type

`hub` —— 单账号下可能有多台泳池机器人。

---

## 二、账号体系与安全授权

### 2.1 现有 OAuth2 服务复用

| 组件 | 路径 | 职责 |
|------|------|------|
| `oauth-server` | `center/oauth-server/` | Spring Authorization Server，已有 Alexa / Google Home 客户端 |
| `SecurityConfig` | `config/oauth/SecurityConfig.java` | OAuth2 协议端点（authorize / token / jwks） |
| `SelfRegisteredClientRepository` | `config/oauth/SelfRegisteredClientRepository.java` | 从 `oauth2_registered_client` 表加载客户端 |
| `CustomAuthenticationProvider` | `config/oauth/CustomAuthenticationProvider.java` | 自定义用户认证（委托 app-auth 校验） |
| `ConsentController` | `controller/ConsentController.java` | 授权同意页（已支持 `device:info` scope） |
| `AppAuthClientProperties` | `config/prop/AppAuthClientProperties.java` | OAuth client → tenant 映射 |

### 2.2 云端改造项

#### 2.2.1 新增 OAuth2 客户端

在 `oauth2_registered_client` 表中插入 HA 客户端记录：

```sql
INSERT INTO oauth2_registered_client (
    client_id, client_secret, client_name,
    authentication_methods, grant_types,
    redirect_uris, post_logout_redirect_uris,
    scopes, client_settings, token_settings
) VALUES (
    'home-assistant',
    -- client_secret 使用 BCrypt 加密存储
    '$2a$10$...',
    'Home Assistant',
    'client_secret_basic',
    'authorization_code,refresh_token',
    -- HA 回调地址（HA Cloud Account Linking 或本地 redirect）
    'https://my.home-assistant.io/redirect/oauth',
    'https://my.home-assistant.io/redirect/oauth',
    'openid,device:info',
    '{"settings.client.require-proof-key":true,"settings.client.require-authorization-consent":true}',
    '{"settings.token.access-token-time-to-live":"PT1H","settings.token.refresh-token-time-to-live":"P30D","settings.token.access-token-format":"self-contained"}'
);
```

#### 2.2.2 租户映射

在 `AppAuthClientProperties` 配置中将 `home-assistant` 加入已有租户：

```yaml
beatbot:
  oauth:
    app-auth-client:
      clients:
        - tenant-id: "1"
          oauth-client-ids:
            - Alexa
            - Google Home
            - home-assistant    # 新增
```

#### 2.2.3 Scope 定义

| Scope | 说明 | 现有状态 |
|-------|------|---------|
| `openid` | OIDC 基础 | 已有 |
| `device:info` | 访问设备列表、状态、控制 | 已有（`ScopeAuthorizationManager` 已校验） |

无需新增 scope，复用 `device:info` 即可。

#### 2.2.4 PKCE 支持

HA 的 OAuth2 config flow 默认使用 PKCE（Proof Key for Code Exchange）。`SelfRegisteredClientRepository` 已支持 `REQUIRE_PROOF_KEY` 配置项，在 `client_settings` 中启用：

```json
{"settings.client.require-proof-key": true}
```

### 2.3 用户绑定模型

| 规则 | 说明                                     |
|------|----------------------------------------|
| 一个 BeatBot 账号 ↔ 一个 HA config entry | config entry 的 `unique_id` 使用 `userId` |
| 多设备归属单用户 | HA 侧通过设备列表 API 获取该用户下所有设备              |
| 多 HA 实例 | 只支持一个 BeatBot 账号 ↔ 一个 HA config                                |

### 2.4 Token 生命周期

```
access_token 有效期:  1 小时
refresh_token 有效期: 30 天

HA 侧:
  - OAuth2Session 自动处理 access_token 刷新
  - refresh_token 过期 → 触发 reauth 流程
  - 用户重新授权 → 更新 config entry 中的 token

云端侧:
  - HA 的 refresh_token 请求由 oauth-server 的 /oauth2/token 端点处理
  - 无需额外改造
```

---

## 三、泳池机器人能力模型与 Entity 设计

### 3.1 HA Entity 映射总览

泳池机器人（`ProductTypeEnum.POOL_ROBOT`）映射为以下 HA Entity：

| 能力 | HA Entity 类型 | Entity ID 命名 | 数据来源（siid/piid） |
|------|---------------|----------------|----------------------|
| 清洁控制（开始/暂停/靠岸） | `vacuum`（StateVacuumEntity） | `vacuum.{device_name}` | 工作状态的 siid/piid |
| 清洁模式 | `select` | `select.{device_name}_clean_mode` | WorkModeEnum 对应 siid/piid |
| 工作状态 | `sensor` | `sensor.{device_name}_status` | WorkStatusEnum 对应 siid/piid |
| 电量 | `sensor`（device_class=battery） | `sensor.{device_name}_battery` | 电量 siid/piid |
| 充电状态 | `binary_sensor` | `binary_sensor.{device_name}_charging` | 充电状态 siid/piid |
| 在线状态 | `binary_sensor`（device_class=connectivity） | `binary_sensor.{device_name}_online` | 设备 online 字段 |
| 错误码 | `sensor`（diagnostic） | `sensor.{device_name}_error` | 错误码 siid/piid |
| 清洁周期 | `sensor`（diagnostic） | `sensor.{device_name}_clean_cycle` | 清洁周期 siid/piid |
| 靠岸按钮 | `button` | `button.{device_name}_dock` | 靠岸指令 siid/piid |
| 固件版本 | `sensor`（diagnostic, entity_category=diagnostic） | `sensor.{device_name}_firmware` | 设备信息接口 |

### 3.2 Vacuum Entity 详细设计

```python
class BeatBotVacuum(StateVacuumEntity):
    """泳池机器人 → HA Vacuum Entity"""

    _attr_supported_features = (
        StateVacuumEntityFeature.START
        | StateVacuumEntityFeature.PAUSE
        | StateVacuumEntityFeature.STOP
        | StateVacuumEntityFeature.RETURN_HOME
        | StateVacuumEntityFeature.BATTERY
        | StateVacuumEntityFeature.STATE
    )

    # HA vacuum state 映射（基于 WorkStatusEnum）
    STATE_MAPPING = {
        0:  STATE_IDLE,       # STANDBY
        1:  STATE_RETURNING,  # GOTO_CHARGE
        2:  STATE_DOCKED,     # Charging
        3:  STATE_DOCKED,     # ChargeDone
        4:  STATE_PAUSED,     # Paused
        5:  STATE_CLEANING,   # Cleaning
        6:  STATE_DOCKED,     # Sleep
        7:  STATE_RETURNING,  # ReturnTrip
        8:  STATE_IDLE,       # CleanDone
        9:  STATE_CLEANING,   # RemoteControl
        10: STATE_IDLE,       # CleanWait
        12: STATE_CLEANING,   # Diving
        13: STATE_CLEANING,   # Emerge
        14: STATE_RETURNING,  # AutoDock
        15: STATE_RETURNING,  # Dock
        17: STATE_CLEANING,   # Draining
        18: STATE_DOCKED,     # ReplenishEnergy
        19: STATE_CLEANING,   # ChaseLight
    }
```

### 3.3 清洁模式 Select Entity

```python
class BeatBotCleanModeSelect(SelectEntity):
    """清洁模式切换"""

    # 基于 WorkModeEnum 定义选项
    OPTIONS = {
        "fast":     0,   # 快速
        "surface":  1,   # 水面
        "standard": 3,   # 标准
        "custom":   2,   # 自定义
        "pro":      4,   # Pro
        "ai":       7,   # AI 清洁
    }
```

### 3.4 云端 Property → HA Entity 映射表

参考现有 `device_property_voice_mapping` 表结构（`DevicePropertyVoiceMappingDO`），新增 `brand = "homeassistant"` 的记录：

| brand | interface_info | instance_name | siid | piid | HA Entity | 说明 |
|-------|---------------|---------------|------|------|-----------|------|
| homeassistant | vacuum.state | - | {siid} | {piid} | vacuum | 工作状态 |
| homeassistant | vacuum.battery | - | {siid} | {piid} | vacuum | 电量 |
| homeassistant | vacuum.fan_speed | - | {siid} | {piid} | vacuum | 吸力/速度 |
| homeassistant | select.clean_mode | work_mode | {siid} | {piid} | select | 清洁模式 |
| homeassistant | sensor.error | - | {siid} | {piid} | sensor | 错误码 |
| homeassistant | button.dock | - | {siid} | {piid} | button | 靠岸指令 |

> 具体 siid/piid 值需根据产品 Thing Model 填充。可参考现有 Alexa mapping 中同一 productId 的记录。

---

## 四、HA 侧集成代码结构

### 4.1 目录结构

```
custom_components/beatbot/
├── __init__.py              # async_setup_entry / async_unload_entry
├── config_flow.py           # OAuth2 config flow + reauth
├── const.py                 # DOMAIN、API 常量、映射表
├── coordinator.py           # DataUpdateCoordinator（设备列表 + 状态轮询）
├── entity.py                # BeatBotEntity 基类（公共属性）
├── vacuum.py                # StateVacuumEntity
├── sensor.py                # Battery / Status / Error sensor
├── button.py                # Dock button
├── select.py                # Clean mode select
├── binary_sensor.py         # Online / Charging binary sensor
├── api.py                   # 云端 API 客户端（aiohttp）
├── models.py                # 数据模型（Device、DeviceState）
├── manifest.json            # domain / iot_class / requirements
├── strings.json             # 翻译文本
├── translations/
│   ├── en.json
│   └── zh-Hans.json
├── icons/
│   └── beatbot.svg          # 品牌 Logo
└── diagnostics.py           # 诊断信息导出（Silver tier 要求）
```

### 4.2 manifest.json

```json
{
  "domain": "beatbot",
  "name": "BeatBot",
  "codeowners": ["@your-github-username"],
  "config_flow": true,
  "dependencies": ["application_credentials"],
  "documentation": "https://www.home-assistant.io/integrations/beatbot",
  "integration_type": "hub",
  "iot_class": "cloud_polling",
  "requirements": [],
  "quality_scale": "bronze",
  "single_config_entry": true
}
```

### 4.3 config_flow.py 设计要点

```python
class BeatBotConfigFlow(AbstractOAuth2FlowHandler, domain=DOMAIN):
    """OAuth2 Config Flow"""

    DOMAIN = DOMAIN

    async def async_step_user(self, user_input=None):
        """发起 OAuth2 授权"""
        return await super().async_step_user(user_input)

    async def async_oauth_create_entry(self, data: dict) -> dict:
        """OAuth 授权完成，创建 config entry"""
        # 1. 用 token 调设备列表 API 验证 token 有效性
        # 2. 获取 userId 作为 unique_id
        # 3. 防止重复配置
        user_id = data["token"]["sub"]  # JWT subject
        await self.async_set_unique_id(user_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="BeatBot", data=data)

    async def async_step_reauth(self, entry_data):
        """token 过期触发 reauth"""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """reauth 确认页面"""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict) -> dict:
        """处理 reauth 场景的 token 更新"""
        user_id = data["token"]["sub"]
        await self.async_set_unique_id(user_id)
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates=data,
            )
        self._abort_if_unique_id_configured()
        return await super().async_oauth_create_entry(data)
```

### 4.4 coordinator.py 设计要点

```python
class BeatBotCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """设备状态轮询协调器"""

    def __init__(self, hass, api: BeatBotAPI):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.api = api
        self.devices: dict[str, Device] = {}

    async def _async_update_data(self) -> dict[str, DeviceState]:
        """拉取所有设备状态"""
        try:
            states = await self.api.get_all_device_states()
            return states
        except BeatBotAuthError as err:
            raise ConfigEntryAuthFailed from err
        except BeatBotConnectionError as err:
            raise UpdateFailed from err
```

### 4.5 __init__.py 入口

```python
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config entry 初始化"""
    # 1. 创建 API 客户端（注入 OAuth2Session）
    api = BeatBotAPI(hass, entry)

    # 2. 创建 Coordinator 并首次刷新
    coordinator = BeatBotCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    # 3. 存储到 hass.data
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # 4. 转发到各 Entity 平台
    await hass.config_entries.async_forward_entry_setups(
        entry, ["vacuum", "sensor", "button", "select", "binary_sensor"]
    )
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载 config entry"""
    return await hass.config_entries.async_unload_platforms(
        entry, ["vacuum", "sensor", "button", "select", "binary_sensor"]
    )
```

---

## 五、云端 API 适配

### 5.1 方案：复用 device-resource-service

参考 Alexa / Google Home 的接入方式，在 `DeviceResourceController` 和 `DeviceServiceImpl` 中新增 `platform=homeassistant` 分支。

#### 5.1.1 现有接口复用

| 接口 | 方法 | 现有用途 | HA 适配 |
|------|------|---------|---------|
| `GET /api/v1/devices?platform={platform}` | 设备发现 | Alexa / Google | 新增 `platform=homeassistant` |
| `GET /api/v1/devices/state/{deviceId}?platform={platform}` | 状态查询 | Alexa / Google | 新增 HA 状态格式 |
| `POST /api/v1/devices/{deviceId}/actions` | 设备控制 | Alexa / Google | 新增 HA 命令翻译 |

#### 5.1.2 设备发现接口改造

`DeviceServiceImpl.getDeviceInAccount()` 新增 HA 分支：

```java
public String getDeviceInAccount(String platform, String userId) {
    if ("homeassistant".equals(platform)) {
        return buildHomeAssistantDiscoveryResponse(userId);
    }
    // 已有 Alexa / Google 逻辑...
}
```

HA 发现响应格式（面向 HA 的 JSON）：

```json
{
  "devices": [
    {
      "deviceId": "xxx",
      "name": "My Pool Robot",
      "model": "i2",
      "manufacturer": "BeatBot",
      "swVersion": "1.2.3",
      "sn": "SN123456",
      "online": true,
      "capabilities": {
        "cleanMode": {"siid": 3, "piid": 1, "options": ["fast","surface","standard","pro","ai"]},
        "workStatus": {"siid": 3, "piid": 2},
        "battery": {"siid": 4, "piid": 1},
        "errorCode": {"siid": 5, "piid": 1}
      }
    }
  ]
}
```

#### 5.1.3 状态查询接口改造

`DeviceServiceImpl.getSingleDeviceState()` 新增 HA 分支：

```java
public String getSingleDeviceState(String platform, String deviceId, String userId) {
    if ("homeassistant".equals(platform)) {
        return buildHomeAssistantStateResponse(deviceId);
    }
    // 已有逻辑...
}
```

HA 状态响应格式：

```json
{
  "deviceId": "xxx",
  "online": true,
  "properties": [
    {"siid": 3, "piid": 1, "value": 3},
    {"siid": 3, "piid": 2, "value": 5},
    {"siid": 4, "piid": 1, "value": 85}
  ]
}
```

#### 5.1.4 设备控制接口改造

`DeviceServiceImpl.handleDeviceCommand()` 新增 HA 命令翻译：

```java
public String handleDeviceCommand(String userId, String deviceId, DeviceActionQuery action) {
    if ("homeassistant".equals(action.getPlatform())) {
        return handleHomeAssistantCommand(userId, deviceId, action);
    }
    // 已有 Alexa / Google 逻辑...
}
```

HA 命令格式（`DeviceActionQuery` 扩展）：

```json
{
  "platform": "homeassistant",
  "action": "start",
  "params": {}
}
```

HA 命令 → 内部 DP 映射：

| HA Action | 映射逻辑 | 内部指令 |
|-----------|---------|---------|
| `start` | 写入工作状态的 Cleaning 值 | `setProperty(siid, piid, 5)` |
| `pause` | 写入工作状态的 Paused 值 | `setProperty(siid, piid, 4)` |
| `stop` | 写入工作状态的 Standby 值 | `setProperty(siid, piid, 0)` |
| `return_to_base` | 写入靠岸指令 | `setProperty(dock siid, dock piid, 1)` |
| `set_clean_mode` | 写入清洁模式值 | `setProperty(mode siid, mode piid, WorkModeEnum.index)` |

### 5.2 Gateway 路由

现有 gateway 配置中 `/device_resource/**` 路由已覆盖 device-resource-service，无需新增路由。

HA 的请求路径为：

```
GET  https://api.beatbot.com/device_resource/api/v1/devices?platform=homeassistant
GET  https://api.beatbot.com/device_resource/api/v1/devices/state/{deviceId}?platform=homeassistant
POST https://api.beatbot.com/device_resource/api/v1/devices/{deviceId}/actions
```

请求头携带 `Authorization: Bearer <access_token>`，由 `device-resource-service` 的 `SecurityConfig`（OAuth2 Resource Server）校验。

### 5.3 product_info_in_voice_platform 表扩展

为 HA 平台新增产品配置记录：

```sql
INSERT INTO product_info_in_voice_platform (
    brand, product_id, model, category, manufacturer, description, enable
) VALUES (
    'homeassistant', '{productId}', 'i2', 'VACUUM_CLEANER',
    'BeatBot', 'BeatBot Robotic Pool Cleaner', true
);
```

---

## 六、状态同步机制

### 6.1 Phase 1：轮询模式（cloud_polling）

```
HA DataUpdateCoordinator
    │
    │ 每 30 秒
    ↓
GET /api/v1/devices/state/{deviceId}?platform=homeassistant
    │
    ↓
更新所有 Entity 状态
```

- `update_interval = 30s`
- 网络异常时 `UpdateFailed` → Coordinator 自动重试
- Token 过期时 `ConfigEntryAuthFailed` → 触发 reauth

### 6.2 Phase 2：事件推送模式（cloud_push，可选增强）

#### 6.2.1 复用现有 Kafka 事件通道

现有 `device-resource-service` 已有三个 Kafka Consumer：

| Consumer | Topic | 事件类型 | HA 复用方式 |
|----------|-------|---------|------------|
| `PropertyChangeReceiver` | property_changed | 属性变更 | 新增 HA 推送分支 |
| `DeviceStatusReceiver` | device_event | 上下线 | 新增 HA 推送分支 |
| `MessageEventReceiver` | device_message | 设备增删改名 | 新增 HA 推送分支 |

#### 6.2.2 推送通道选型

| 方案 | 优点 | 缺点 |
|------|------|------|
| WebSocket | 实时性好，HA 有 `websocket_api` 支持 | 需维护长连接 |
| SSE（Server-Sent Events） | 单向推送，实现简单 | HA 侧需 aiohttp SSE client |
| Webhook | HA 提供 webhook endpoint | 需云端存储 webhook URL |

推荐 **WebSocket**，与 HA 的连接管理最成熟。

#### 6.2.3 推送数据格式

```json
{
  "type": "property_changed",
  "deviceId": "xxx",
  "properties": [
    {"siid": 3, "piid": 2, "value": 5}
  ],
  "timestamp": 1718000000
}
```

```json
{
  "type": "device_status",
  "deviceId": "xxx",
  "online": false,
  "timestamp": 1718000000
}
```

### 6.3 状态一致性策略

| 场景 | 策略 |
|------|------|
| 正常轮询 | 30s 内最终一致 |
| 控制命令后 | 立即调状态查询 API 获取最新快照 |
| 网络中断 | HA Coordinator 自动重试，恢复后全量刷新 |
| Token 过期 | 触发 reauth，用户重新授权后恢复 |
| 设备离线 | `online` 字段为 0 → Entity 标记 `unavailable` |

---

## 七、云端改造清单

### 7.1 oauth-server 模块

| 改动 | 文件 | 说明 |
|------|------|------|
| 新增 HA OAuth client | `oauth2_registered_client` 表 | SQL 插入 |
| 新增租户映射 | `application.yml` | `oauth-client-ids` 列表追加 `home-assistant` |
| 同意页文案 | `consent.html` + `ConsentController` | 可选：针对 HA 优化显示文案 |

### 7.2 device-resource-service 模块

| 改动 | 文件 | 说明 |
|------|------|------|
| HA 设备发现 | `DeviceServiceImpl.getDeviceInAccount()` | 新增 `homeassistant` 分支 |
| HA 状态查询 | `DeviceServiceImpl.getSingleDeviceState()` | 新增 HA 状态格式 |
| HA 命令控制 | `DeviceServiceImpl.handleDeviceCommand()` | 新增 HA 命令翻译 |
| HA 属性映射 | `DevicePropertyVoiceMappingDO` 表 | 新增 `brand=homeassistant` 记录 |
| HA 产品配置 | `ProductInfoInVoicePlatformDO` 表 | 新增 `brand=homeassistant` 记录 |
| HA 状态推送（Phase 2） | `PropertyChangeReceiver` / `DeviceStatusReceiver` | 新增 HA 推送通道 |
| HA 设备生命周期（Phase 2） | `MessageEventReceiver` | 新增 HA 设备增删事件 |

### 7.3 Gateway 模块

无需改动。现有路由已覆盖：
- `/oauth2/**` → oauth-server
- `/device_resource/**` → device-resource-service

---

## 八、HA 侧 Python API 客户端

### 8.1 api.py 核心方法

```python
class BeatBotAPI:
    """BeatBot 云端 API 客户端"""

    BASE_URL = "https://api.beatbot.com"

    def __init__(self, hass, entry: ConfigEntry):
        self._hass = hass
        self._entry = entry
        self._session = OAuth2Session(hass, entry, Implementation(...))

    async def get_devices(self) -> list[Device]:
        """获取设备列表"""
        resp = await self._session.request(
            "GET",
            f"{self.BASE_URL}/device_resource/api/v1/devices",
            params={"platform": "homeassistant"},
        )
        return [Device.from_dict(d) for d in resp["devices"]]

    async def get_device_state(self, device_id: str) -> DeviceState:
        """获取单设备状态"""
        resp = await self._session.request(
            "GET",
            f"{self.BASE_URL}/device_resource/api/v1/devices/state/{device_id}",
            params={"platform": "homeassistant"},
        )
        return DeviceState.from_dict(resp)

    async def send_command(self, device_id: str, action: str, params: dict = None):
        """发送控制指令"""
        await self._session.request(
            "POST",
            f"{self.BASE_URL}/device_resource/api/v1/devices/{device_id}/actions",
            json={
                "platform": "homeassistant",
                "action": action,
                "params": params or {},
            },
        )
```

### 8.2 异常处理

```python
class BeatBotAuthError(Exception):
    """Token 过期或无效 → 触发 reauth"""

class BeatBotConnectionError(Exception):
    """网络异常 → Coordinator 重试"""

class BeatBotDeviceOfflineError(Exception):
    """设备离线 → Entity unavailable"""
```

---

## 九、测试计划

### 9.1 功能测试

| 测试项 | 验证内容 | 通过标准 |
|--------|---------|---------|
| OAuth 登录 | 用户在 HA 发起 OAuth → 跳转 BeatBot 登录 → 授权 → 回调 | config entry 创建成功，token 存储正确 |
| Token 刷新 | access_token 过期后自动刷新 | 无感知刷新，Entity 持续可用 |
| reauth | refresh_token 过期 → HA 提示重新授权 | reauth 流程正常，token 更新 |
| 设备发现 | 添加集成后自动发现所有泳池机器人 | 设备数量、名称、型号正确 |
| 设备控制-开始 | HA 点击 Start → 设备开始清洁 | 设备响应，状态同步到 Cleaning |
| 设备控制-暂停 | HA 点击 Pause → 设备暂停 | 设备响应，状态同步到 Paused |
| 设备控制-靠岸 | HA 点击 Return → 设备靠岸 | 设备响应，状态同步到 Returning |
| 模式切换 | HA Select 切换清洁模式 | 设备模式变更，状态同步 |
| 电量显示 | sensor 显示实时电量 | 数值与 App 一致 |
| 在线状态 | binary_sensor 显示在线/离线 | 与设备实际状态一致 |
| 设备离线 | 设备断网 → Entity unavailable | 30s 内标记为 unavailable |
| 多设备 | 同账号下多台机器人 | 每台机器人独立 Entity |
| 卸载集成 | 移除集成 → 清理所有 Entity | 无残留 Entity |

### 9.2 稳定性测试

| 测试项 | 验证内容 |
|--------|---------|
| 多设备同时控制 | 同时向 3 台设备发送指令，无超时 |
| Token 过期恢复 | 手动使 token 失效 → reauth 自动触发 |
| 网络中断恢复 | 断开网络 5 分钟 → 恢复后状态自动同步 |
| 长时间运行 | 集成连续运行 72h，无内存泄漏 |
| 设备频繁上下线 | 设备 1 分钟内上下线 10 次 → Entity 状态正确 |

### 9.3 HA 兼容性验证

| 验证项 | 说明 |
|--------|------|
| vacuum Entity 行为 | `vacuum.start/pause/stop/return_to_base` 服务调用正常 |
| State 更新 | vacuum 的 `state` 属性符合 HA 预定义值（cleaning/paused/returning/docked/idle/error） |
| Entity 生命周期 | 设备删除后 Entity 自动移除，设备新增后 Entity 自动创建 |
| Device Registry | Device 信息（manufacturer/model/sw_version）正确注册 |
| UI 展示 | vacuum 卡片、Entity 卡片展示正常 |
| Automation | 可基于 Entity 状态创建自动化规则 |

---

## 十、HA 官方审核准备

### 10.1 Quality Scale 目标

| Tier | 要求 | 状态 |
|------|------|------|
| Bronze | config_flow + 基本 Entity + 文档 | Phase 1 目标 |
| Silver | + diagnostics + 完整测试覆盖 | Phase 2 目标 |
| Gold | + repair + 异步卸载 + 严格类型检查 | 后续迭代 |

### 10.2 审核 Checklist

- [ ] manifest.json 字段完整（domain / name / iot_class / integration_type / config_flow / quality_scale）
- [ ] config_flow.py 实现 reauth 流程
- [ ] 所有 config_flow 步骤有 strings.json 翻译
- [ ] Entity unique_id 稳定（使用 deviceId + entity 类型后缀）
- [ ] Device 信息注册到 device_registry（manufacturer / model / sw_version）
- [ ] 网络异常有合理的异常处理和重试
- [ ] Token 过期触发 reauth
- [ ] 卸载集成时清理所有资源（aiohttp session / listener / timer）
- [ ] diagnostics.py 导出脱敏诊断信息
- [ ] config_flow.py 100% 测试覆盖
- [ ] 无硬编码密钥或敏感信息
- [ ] 异步代码无 blocking call（使用 `asyncio` 或 `executor`）

### 10.3 交付物清单

| 交付物 | 说明 |
|--------|------|
| `custom_components/beatbot/` | HA 集成代码 |
| 云端 SQL 脚本 | OAuth client + property mapping + product config |
| 云端 Java 改动 | device-resource-service HA 分支 |
| 测试计划 + 测试用例 | 见第九章 |
| API 文档 | HA 侧使用的 3 个 API 接口说明 |
| Entity 行为文档 | 各 Entity 的 state 映射和 supported_features |

---

## 十一、开发阶段

### Phase 1：基础集成（2 周）

| 周次 | 任务 | 交付 |
|------|------|------|
| W1 | 云端：OAuth client 注册 + 租户映射 | OAuth 流程跑通 |
| W1 | 云端：HA 设备发现接口（`getDeviceInAccount`） | 设备列表 API 可用 |
| W1 | HA 侧：config_flow + OAuth2 + __init__ | 集成安装 + 登录 |
| W2 | 云端：HA 状态查询接口（`getSingleDeviceState`） | 状态 API 可用 |
| W2 | 云端：HA 命令控制接口（`handleDeviceCommand`） | 控制 API 可用 |
| W2 | HA 侧：coordinator + vacuum + sensor + select + button | 全功能 Entity |

### Phase 2：稳定性与审核（1 周）

| 周次 | 任务 | 交付 |
|------|------|------|
| W3 | HA 侧：diagnostics + repair + reauth 测试 | 完善集成质量 |
| W3 | 联调测试：功能 + 稳定性 + 兼容性 | 测试报告 |
| W3 | 审核准备：文档 + checklist + PR 提交 | 提交 HA Core PR |

### Phase 3（可选）：推送增强

| 任务 | 交付 |
|------|------|
| 云端：WebSocket 推送通道 | 实时状态推送 |
| HA 侧：WebSocket client + cloud_push | iot_class 升级 |
| Kafka Consumer 新增 HA 分支 | 事件驱动同步 |

---

## 十二、关键参考文件索引

| 文件 | 路径 | 说明 |
|------|------|------|
| DeviceResourceController | `center/device-resource-service/.../controller/DeviceResourceController.java` | 设备资源 API 入口 |
| DeviceServiceImpl | `center/device-resource-service/.../service/impl/DeviceServiceImpl.java` | 平台命令翻译核心 |
| AlexaRelationMsgBuilder | `center/device-resource-service/.../util/AlexaRelationMsgBuilder.java` | 消息构建参考 |
| InternalDeviceService | `center/device-resource-service/.../call/InternalDeviceService.java` | 内部 API 调用 |
| DevicePropertyVoiceMappingDO | `center/device-resource-service/.../entity/model/DevicePropertyVoiceMappingDO.java` | 属性映射表模型 |
| ProductInfoInVoicePlatformDO | `center/device-resource-service/.../entity/model/ProductInfoInVoicePlatformDO.java` | 产品平台配置模型 |
| DeviceAttachVoiceDO | `center/device-resource-service/.../entity/model/DeviceAttachVoiceDO.java` | 设备平台绑定模型 |
| ThirdAuthInfoDO | `center/device-resource-service/.../entity/model/ThirdAuthInfoDO.java` | 第三方 Token 存储 |
| PropertyChangeReceiver | `center/device-resource-service/.../consumer/PropertyChangeReceiver.java` | 属性变更事件 |
| DeviceStatusReceiver | `center/device-resource-service/.../consumer/DeviceStatusReceiver.java` | 设备上下线事件 |
| MessageEventReceiver | `center/device-resource-service/.../consumer/MessageEventReceiver.java` | 设备生命周期事件 |
| SecurityConfig (OAuth) | `center/oauth-server/.../config/oauth/SecurityConfig.java` | OAuth2 配置 |
| SelfRegisteredClientRepository | `center/oauth-server/.../config/oauth/SelfRegisteredClientRepository.java` | OAuth 客户端管理 |
| AppAuthClientProperties | `center/oauth-server/.../config/prop/AppAuthClientProperties.java` | 租户映射配置 |
| WorkModeEnum | `common/common-constant/.../enums/deviceResource/WorkModeEnum.java` | 清洁模式枚举 |
| WorkStatusEnum | `common/common-constant/.../enums/deviceResource/WorkStatusEnum.java` | 工作状态枚举 |
| DeviceVO | `center/app-device/.../entity/vo/DeviceVO.java` | 设备列表 VO |
| Gateway 路由配置 | `gateway/src/main/resources/application*.yml` | 路由规则 |
