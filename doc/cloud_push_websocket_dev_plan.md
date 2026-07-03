# Cloud Push（WebSocket）接入开发方案

> Phase 2：在现有 30s 轮询（`cloud_polling`）之上叠加一层云端 WebSocket 推送，实现设备状态变更的低延迟透传。
>
> **定位**：event 不是替代 poll，而是 poll 之上的一层增量通道。poll 仍是全量 reconciliation 的 source of truth。

---

## 一、背景与目标

### 1.1 现状（Phase 1）

```
config_flow.py（OAuth2 授权码，region 路由）
    ↓
__init__.py::async_setup_entry
    ↓
coordinator.py（DataUpdateCoordinator，30s 全量轮询）
    ├─ api.get_devices()          /openapi/v1/devices          （discovery：身份+能力）
    └─ api.get_device_states()    /openapi/v1/devices/state    （batch state）
    ↓
apply_state(device, states, is_online)   # 原地 overlay 到 BeatbotDeviceData
    ↓
vacuum / sensor / binary_sensor / select 实体
```

外加一条 post-control 路径：用户下发命令（start/pause/return/work_mode）后，`async_schedule_device_state_refresh` 延迟 3s 单设备拉一次 state 确认。

### 1.2 目标

- 设备状态变更（`vacuum.state` / `vacuum.battery` / `sensor.error` / `select.work_mode` / `isOnline`）发生后，秒级反映到 HA 实体，而不是等下一个 30s。
- 不破坏 Phase 1 的容错语义：fetch 失败保留上次值、auth 失败升级 reauth、超时 30s 边界、staleness 门控 `available`。
- event 通道自身故障时，无缝回退到 30s poll，用户无感。

### 1.3 后端契约依赖（待确认）

> 下文凡标 **[BE: 待确认]** 的字段/端点都需与 beatbot-cloud 侧对齐。后端已有给 Alexa/Google 用的 Kafka `PropertyChangeReceiver` / `DeviceStatusReceiver`（见《Home-Assistant集成开发方案》1.1），HA 推送通道大概率复用同一事件源，新增一个 WebSocket 出口。

必须落实的后端契约项：

| 项 | 说明 |
|----|------|
| WebSocket 端点 URL | 按 region（cn/na/eu），与 `REGION_API_BASE_URL` 同域 **[BE: 待确认]** |
| 鉴权方式 | `Authorization: Bearer <jwt>` 子协议握手，或连接后发 auth 帧 **[BE: 待确认]** |
| 订阅范围 | 账号级（一条连接收该账号所有已授权设备）还是按 deviceId 订阅 **[BE: 待确认]** |
| 事件帧 schema | `{deviceId, interfaceInfo, value, isOnline?, timestamp?, seq?}` **[BE: 待确认]** |
| 心跳 | 服务端 ping 间隔、期望客户端 pong **[BE: 待确认]** |
| 离线缓冲 | 连接断开期间的事件是否在后端累计、重连后重放 **[BE: 待确认]** |

---

## 二、当前状态设计约束（cloud_push 必须遵守）

这部分是 event 接入的「不变量」，直接复用现有逻辑，不要另起一套。

### 2.1 数据模型

- 单一数据载体：`coordinator.data: dict[device_id, BeatbotDeviceData]`（`models.py`）。
- 实体读 `self.data.<field>`，不缓存。所以只要 `coordinator.data` 被正确 overlay + `async_set_updated_data` 推送，所有实体自动刷新。
- 状态映射（`work_status` → `VacuumActivity` / display slug、`error_code` 位拆解）按 category 写死在 HA 端（`iot/category.py`），**不走后端 config 驱动**。event 只负责把原始 code 喂进 `BeatbotDeviceData`，映射复用现有表。

### 2.2 增量 overlay

`iot/mapping.py::apply_state(device, states, is_online)` 已经是「按 `interfaceInfo` → 字段」的部分 overlay，**不是整对象替换**。event 增量推送天然复用它：

```python
apply_state(device, {"vacuum.state": 5}, is_online=None)
```

`HA_STATE_FIELD_MAP` 已覆盖四个状态键（`vacuum.state` / `vacuum.battery` / `sensor.error` / `select.work_mode`）。event 帧里的 `interfaceInfo` 只要落在这些键内即可，无需新映射。

### 2.3 `is_online` 语义（关键）

- `is_online` 仅来自 poll / 后端心跳，**不来自 WS 连接状态**。
- 现有行为：`get_device_states` 整体失败时 `states={}`，`apply_state` 不覆盖 `is_online`，保留上次值 —— 即「后端断网 ≠ 设备离线」。
- cloud_push 必须保持：WS 断线只记日志 + 触发重连，**绝不**把 `is_online` 置 False，否则传输抖动会让设备在 HA 里频繁闪 offline。

### 2.4 staleness 门控

- 实体 `available = self.data.is_online and self.coordinator.last_update_success`（`vacuum.py` / `select.py` / `BeatbotChargingSensor`）。
- `BeatbotOnlineSensor` 未覆写 `available`，继承 `CoordinatorEntity` 默认（`last_update_success`）。
- 含义：event 通道故障时，只要 poll 还成功，实体仍 available；poll 也连续失败时实体灰掉。cloud_push 不需要额外动 `available`。

### 2.5 错误翻译

- poll 路径：`BeatbotAuthError → ConfigEntryAuthFailed`，`BeatbotConnectionError → UpdateFailed`（保留上次数据）。
- 命令路径：`_async_send_command`（`entity.py`）统一 `BeatbotAuthError → ConfigEntryAuthFailed`、`BeatbotConnectionError → HomeAssistantError`，并前置 `is_online` guard。
- HTTP 请求 30s 超时（`BEATBOT_HOME_HTTP_API_TIMEOUT` + `aiohttp.ClientTimeout`）。
- event 通道的错误处理走同一套语义（见 §6）。

### 2.6 post-control refresh

- 命令下发后 `async_schedule_device_state_refresh` 延迟 3s 单设备拉 state。
- 有了 event 之后，这条路径**保留**：它是用户主动操作的去抖确认，event 可能比命令回执更早到达造成抖动。两条路径互补，不互斥。

---

## 三、传输层设计

### 3.1 模块划分

新增 `custom_components/beatbot_home/iot/event_stream.py`，封装一条长连接 WS：

```
event_stream.py
  └─ BeatbotEventClient
       ├─ connect()              # 握手 + 订阅
       ├─ _recv_loop()           # 主循环：收帧 → 路由到 coordinator
       ├─ _heartbeat()           # ping/pong 看门狗
       ├─ _reconnect()           # 指数退避重连
       └─ stop()                 # 幂等关闭
```

不放进 `api.py`：`BeatbotAPI` 是无状态请求/响应客户端，WS 是有状态长连接，生命周期不同，分开更清晰。

### 3.2 连接与鉴权

- 复用 `OAuth2Session` 取 access_token。WS 握手 header 带 `Authorization: Bearer <token>`（或子协议，**[BE: 待确认]**）。
- **token 刷新难题**：WS header 一旦握手成功就无法中途换 token。策略：
  1. 连接前 `await session.async_ensure_token_valid()` 拿最新 token。
  2. 服务端返回 401/close code（鉴权失败）→ 触发一次 token 刷新 → 重连。
  3. 刷新本身失败（`BeatbotAuthError`）→ 升级 `ConfigEntryAuthFailed`，与 poll/命令路径一致。
- region 路由：与 `BeatbotAPI` 同一套 `REGION_API_BASE_URL` + `DEV_MODE` 逻辑，抽成共享 helper 避免两处漂移。

### 3.3 重连策略

- 指数退避：1s → 2s → 4s → ... 封顶 60s，加 ±20% 抖动（避免羊群效应）。
- 重连期间不污染 `coordinator.data` / `is_online`，只记日志。
- 连续失败 N 次（如 10 次）后降级：仅记 warning，退化为纯 poll 模式，但仍周期性尝试重连（每 5min 一次探活）。
- 重连必须幂等：旧连接的 in-flight 任务要 cancel，避免双收。

### 3.4 心跳 / 看门狗

- 若后端发 ping：响应 pong，并跟踪 `last_pong` 时间戳。
- 若后端不发：客户端周期发 ping，超时未收 pong 主动 close 触发重连。
- 超过 `heartbeat_timeout`（建议 2~3 倍 ping 间隔）无任何帧 → 认为连接已死，close + 重连。

---

## 四、Coordinator 集成

### 4.1 新增入口方法

`coordinator.py` 加一个增量写入入口，复用 `apply_state` + `async_set_updated_data`：

```python
async def async_apply_device_event(
    self,
    device_id: str,
    states: dict | None,
    is_online: bool | None = None,
    seq: int | None = None,
) -> None:
    """Apply a single incremental event to one device and push to entities.

    Reuses apply_state (partial overlay, not full replace) and
    async_set_updated_data. Does NOT reset the poll timer — events are
    steady-state traffic, resetting on every frame would distort the
    30s poll cadence (post-control refresh resets precisely because it
    is a user-initiated debounce, not steady traffic).
    """
    device = self.data.get(device_id)
    if device is None:
        # Event for a device not yet discovered — ignore; poll will
        # discover it and subsequent events will land.
        return
    # [BE: 待确认] seq-based dedup if backend provides a sequence number.
    apply_state(device, states, is_online)
    self.async_set_updated_data(self.data)
```

设计要点：

- **不 reset poll 定时器**（与 post-control 路径不同）。
- 设备未在 `coordinator.data` 中：丢弃该帧。discovery 仍由 poll 负责，event 一般不携带身份/能力信息。下一轮 poll 发现设备后，后续 event 自然命中。
- `is_online=None` 时不覆盖（`apply_state` 已处理），保证 §2.3 的语义。

### 4.2 不要做的事

| 反模式 | 原因 |
|--------|------|
| 用 event 整对象替换 `coordinator.data[device_id]` | event 是增量，整替换会丢 discovery 字段（productId/capabilities/versions） |
| event 到达时 `async_update_interval` 重置 | 会把 30s 节奏打乱成事件驱动 |
| WS 断线时 `device.is_online = False` | 传输故障 ≠ 设备离线（§2.3） |
| 为 event 改 `STATUS_MAP` / `ERROR_BITS` | 映射按 category 写死 HA 端，event 只喂原始 code |
| 在 event 路径做命令重试 | event 是状态下行，不是命令 ACK；命令重试是另一回事 |

---

## 五、一致性模型（核心）

### 5.1 角色分工

| 通道 | 频率 | 数据范围 | 角色 |
|------|------|----------|------|
| poll | 30s（可放宽） | 全量 discovery + 全量 state | source of truth / reconciliation |
| event | 实时 | 单字段增量（per interfaceInfo） | 低延迟透传 |
| post-control refresh | 命令后 3s 一次 | 单设备全量 state | 用户操作的去抖确认 |

三者并存、互补、不互斥。

### 5.2 冲突解决

同一字段 poll 与 event 都写时：

1. **优先用 seq/timestamp**（若后端提供 **[BE: 待确认]**）：丢弃 `seq <= 已应用 seq` 的事件。
2. 无 seq 时 **last-write-wins**：以到达顺序为准。event 通常比 poll 新，所以 event 覆盖 poll；下一轮 poll 又做全量纠偏。
3. poll 永远是兜底：即便 event 丢/乱序，下一轮 30s poll 会用全量 state 修正所有字段。所以 event 的弱一致是可接受的。

### 5.3 幂等性

- `apply_state` 是 `setattr`，同值重复写无副作用。
- 实体 `async_write_ha_state` 容忍重复调用。
- 所以 event 重复投递（重连后重放）安全，只要 seq 去重生效或不介意 last-write-wins。

### 5.4 poll 节奏放宽（二期，可选）

event 稳定运行一段时间后，可把 `NETWORK_REFRESH_INTERVAL` 从 30s 放宽到 300s，省请求。但：

- **discovery（设备列表/能力）仍必须靠 poll** —— event 一般不推新设备上线/能力变更。
- 放宽前先观察 event 通道稳定性（重连频率、丢帧率），不稳就保持 30s。
- 放宽是改一个常量，可灰度。

---

## 六、失败与恢复矩阵

| 场景 | 行为 | 是否影响 `is_online` | 是否影响 `available` |
|------|------|----------------------|----------------------|
| WS 连接断开 | 退避重连，记 log | 否 | 否（poll 仍成功） |
| WS 重连连续失败 N 次 | 降级纯 poll，5min 探活 | 否 | 否 |
| WS 收到 401/close-auth | 刷 token 重连一次；刷新失败 → `ConfigEntryAuthFailed` | 否 | 触发 reauth flow |
| event 帧 schema 异常 | 丢帧 + warning，不断连 | 否 | 否 |
| event 未知 deviceId | 丢帧（等 poll discovery） | 否 | 否 |
| poll 连续失败 | `last_update_success=False` | `is_online` 保留上次 | 实体灰掉 |
| 设备真实离线（后端 `isOnline=False`） | poll/event 写 `is_online=False` | 是 | 实体灰掉 |

---

## 七、生命周期

### 7.1 启动（`__init__.py::async_setup_entry`）

```python
coordinator = BeatbotCoordinator(hass, api)
await coordinator.async_config_entry_first_refresh()

event_client = BeatbotEventClient(hass, api, coordinator)
hass.data[DOMAIN][entry.entry_id] = {
    "coordinator": coordinator,
    "api": api,
    "session": session,
    "event_client": event_client,
}
# 后台启动 WS，不阻塞 setup
event_client.async_start()
```

- `async_start` 内部 `hass.async_create_task(self._run())`，任务引用存 `event_client._task`。
- setup 不等待 WS 连接成功 —— poll 已经能提供数据，WS 是增量。

### 7.2 卸载（`async_unload_entry`）

```python
data = hass.data[DOMAIN][entry.entry_id]
if data.get("event_client") is not None:
    await data["event_client"].async_stop()
if data.get("coordinator") is not None:
    data["coordinator"].async_cancel_pending_refreshes()
```

- `async_stop`：cancel `_task`，close WS，幂等。
- 与现有 `async_cancel_pending_refreshes` 同样模式，避免任务在 session 拆除后还触发。

---

## 八、常量新增（`iot/const.py`）

```python
# WebSocket push channel (Phase 2 cloud_push). Region-routed like the
# REST API; endpoints per region [BE: 待确认].
EVENT_WS_PATH: str = '/openapi/v1/events'  # [BE: 待确认]

REGION_WS_BASE_URL: dict[str, str] = {
    'cn': 'wss://cn-iot.beatbot.com',
    'na': 'wss://na-iot.beatbot.com',
    'eu': 'wss://eu-iot.beatbot.com',
}

# Reconnect backoff for the event WS.
EVENT_RECONNECT_MIN_DELAY: float = 1.0
EVENT_RECONNECT_MAX_DELAY: float = 60.0
EVENT_RECONNECT_MAX_ATTEMPTS: int = 10  # 之后降级为探活模式
EVENT_PROBE_INTERVAL: int = 300  # 降级后探活间隔（秒）

# Heartbeat / watchdog.
EVENT_HEARTBEAT_INTERVAL: int = 30   # [BE: 待确认] 对齐服务端 ping
EVENT_HEARTBEAT_TIMEOUT: int = 90    # 无任何帧即判定连接已死
```

> `DEV_MODE` 下 WS 也应走本地或跳过，与 REST 一致。

---

## 九、测试计划（`tests/test_event_stream.py`）

用 `aiohttp.test_utils` 或 `pytest-aiohttp` 起一个 mock WS server，覆盖：

| 用例 | 断言 |
|------|------|
| 正常帧路由 | `coordinator.async_apply_device_event` 被调用，实体字段更新 |
| 401 关闭 | 触发一次 token 刷新 + 重连；刷新失败抛 `ConfigEntryAuthFailed` |
| 断线重连 | 退避延迟单调递增、封顶 60s |
| 重复帧 / 乱序 | seq 去重生效（若后端提供 seq） |
| 未知 deviceId | 丢帧不抛异常 |
| schema 异常帧 | 丢帧 + 不断连 |
| 心跳超时 | 无帧超过 timeout → close + 重连 |
| `async_stop` | 任务 cancel、WS close、幂等（重复调用安全） |
| unload entry | `event_client` 与 `_refresh_tasks` 都被清理 |
| `is_online` 不被 WS 断线污染 | 断线后 `coordinator.data[id].is_online` 不变 |
| poll + event 并发 | event overlay 后 poll 全量纠偏一致 |

`coordinator.async_apply_device_event` 单测（不依赖 WS）：构造 event payload → 调用 → 断言 `data` 字段 + `last_update_success` + poll 定时器未重置。

---

## 十、落地步骤（建议顺序）

1. **后端契约对齐**：落实 §1.3 表格所有 **[BE: 待确认]** 项，否则无法编码。
2. **`coordinator.async_apply_device_event`**：先加这个方法 + 单测，不动传输层。这是 event 接入的「接收端」，可独立验证。
3. **`iot/event_stream.py` 骨架**：connect / recv_loop / stop，无重连，mock server 跑通正常帧。
4. **重连 + 心跳**：退避、token 刷新、看门狗。
5. **生命周期接入**：`__init__.py` 启停。
6. **集成测试**：§9 全量。
7. **灰度**：先 `DEV_MODE` 本地验证，再切 region；保持 30s poll 不变。
8. **（二期）poll 放宽**：观察稳定后再调 `NETWORK_REFRESH_INTERVAL`。

---

## 十一、开放问题

- **后端是否提供 seq/timestamp**：决定去重策略是强一致还是 last-write-wins（§5.2）。
- **断线期间事件是否累积重放**：若是，重连后可能收到一大波旧事件 —— seq 去重必备；若否，丢的 event 靠 poll 兜底。
- **一条连接 vs 每设备一条连接**：账号级单连接最简，设备数多时后端可能限流，需确认。
- **WS 与现有 Alexa/Google Kafka 通道的关系**：能否复用同一事件源、只是换个出口协议。
- **DEV_MODE 下 WS 如何测**：本地是否起 mock WS server，还是直接跳过 event 通道。
