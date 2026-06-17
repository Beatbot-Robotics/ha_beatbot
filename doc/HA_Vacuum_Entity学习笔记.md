# Vacuum Entity 学习笔记（泳池清洁机器人版）

> 基于官方文档 [developers.home-assistant.io/docs/core/entity/vacuum](https://developers.home-assistant.io/docs/core/entity/vacuum) 整理，专为 Beatbot **泳池清洁机器人**适配。

---

## 一、Vacuum Entity 是什么？

**一句话：Vacuum 是清洁机器人专属 entity，是 Beatbot 集成的核心主实体。**

HA 的 vacuum 领域不仅限于扫地机，**所有自主移动的清洁机器人都用 vacuum entity**——包括泳池清洁机器人。

继承自 `StateVacuumEntity`。

---

## 二、状态（VacuumActivity）

**必须实现 `activity` 属性**，返回以下枚举值之一：

| VacuumActivity | 含义 | 泳池机器人场景 |
|---------------|------|--------------|
| `CLEANING` | 正在清洁 | 清洁中、遥控、清洁等待、下潜、浮出、自清洁、追光 |
| `DOCKED` | 在充电座上（含充电） | 充电中、充电完成、靠岸完成 |
| `IDLE` | 空闲（未暂停、未回充、无错误） | 待机、休眠、清洁完成、WiFi连接、连接完成、补能中 |
| `PAUSED` | 暂停（清洁中被暂停，未靠岸） | 用户暂停清洁 |
| `RETURNING` | 正在返回充电座 | 回座中、回程、自动靠岸、一键靠岸 |
| `ERROR` | 遇到错误 | 设备报错 |

### Beatbot WorkStatusEnum → VacuumActivity 映射

根据项目设计文档 `Home-Assistant集成开发方案.md` 中的映射表：

| WorkStatusEnum 值 | 含义 | VacuumActivity | 分组 |
|-------------------|------|---------------|------|
| 0 standby | 待机中 | `IDLE` | 空闲 |
| 1 goto_charge | 回座中 | `RETURNING` | 靠岸 |
| 2 charging | 充电中 | `DOCKED` | 在岸上 |
| 3 charge_done | 充电完成 | `DOCKED` | 在岸上 |
| 4 paused | 暂停 | `PAUSED` | 暂停 |
| 5 cleaning | 清扫中 | `CLEANING` | 工作中 |
| 6 sleep | 休眠 | `IDLE` | 空闲 |
| 7 return_trip | 回程 | `RETURNING` | 靠岸 |
| 8 clean_done | 清洁完成 | `IDLE` | 空闲 |
| 9 remote_control | 遥控中 | `CLEANING` | 工作中 |
| 10 clean_wait | 清洁等待 | `CLEANING` | 工作中 |
| 11 wifi_connect | WiFi连接 | `IDLE` | 空闲 |
| 12 diving | 潜水 | `CLEANING` | 工作中 |
| 13 emerge | 出水 | `CLEANING` | 工作中 |
| 14 auto_dock | 自动靠岸 | `RETURNING` | 靠岸 |
| 15 dock | 一键靠岸 | `RETURNING` | 靠岸 |
| 16 finish_connect | 连接完成 | `IDLE` | 空闲 |
| 17 self_cleaning | 自清洁中 | `CLEANING` | 工作中 |
| 18 replenish_energy | 补能中 | `IDLE` | 空闲 |
| 19 chase_light | 追光中 | `CLEANING` | 工作中 |
| 20 dock_done | 靀岸完成 | `DOCKED` | 靠岸 |

```python
from homeassistant.components.vacuum import VacuumActivity

STATUS_MAP: dict[int, VacuumActivity] = {
    0: VacuumActivity.IDLE,
    1: VacuumActivity.RETURNING,
    2: VacuumActivity.DOCKED,
    3: VacuumActivity.DOCKED,
    4: VacuumActivity.PAUSED,
    5: VacuumActivity.CLEANING,
    6: VacuumActivity.IDLE,
    7: VacuumActivity.RETURNING,
    8: VacuumActivity.IDLE,
    9: VacuumActivity.CLEANING,
    10: VacuumActivity.CLEANING,
    11: VacuumActivity.IDLE,
    12: VacuumActivity.CLEANING,
    13: VacuumActivity.CLEANING,
    14: VacuumActivity.RETURNING,
    15: VacuumActivity.RETURNING,
    16: VacuumActivity.IDLE,
    17: VacuumActivity.CLEANING,
    18: VacuumActivity.IDLE,
    19: VacuumActivity.CLEANING,
    20: VacuumActivity.DOCKED,
}


@property
def activity(self) -> VacuumActivity:
    if self._device.error_code != 0:
        return VacuumActivity.ERROR
    return STATUS_MAP.get(self._device.work_status, VacuumActivity.IDLE)
```

> **优先级：error_code != 0（任一故障位非零）→ 强制 ERROR，否则按 STATUS_MAP 映射。vacuum ERROR 表示"设备有故障"，7 个 binary_sensor.error_*（device_class=PROBLEM）表示"具体哪些故障同时存在"。error_code 是位掩码，不能用 ENUM——位组合值不在固定选项列表内。**

---

## 三、Supported Features（必须声明 STATE）

| Feature | 含义 | Beatbot 要声明吗？ | 需要实现的方法 |
|---------|------|-------------------|--------------|
| `STATE` | 能返回当前状态 | ✅ **必须** | `activity` 属性 |
| `START` | 能开始清洁 | ✅ | `async_start` |
| `PAUSE` | 能暂停清洁 | ✅ | `async_pause` |
| `STOP` | 能停止清洁 | ✅ | `async_stop` |
| `RETURN_HOME` | 能靠岸回充 | ✅ | `async_return_to_base` |
| `FAN_SPEED` | 能调吸力/速度 | ❌ | `fan_speed` + `async_set_fan_speed` |
| `LOCATE` | 能定位/寻找 | ❌ | `async_locate` |
| `CLEAN_SPOT` | 能局部清洁 | ❌  | `async_clean_spot` |
| `CLEAN_AREA` | 能按区域清洁 | ❌  | `async_get_segments` + `async_clean_segments` |
| `MAP` | 能获取地图 | 看API | — |
| `SEND_COMMAND` | 能发自定义命令 | ❌ | `async_send_command` |


> **注意：泳池清洁机器人没有"房间/区域"概念（CLEAN_AREA），也没有"吸力档位"概念（FAN_SPEED），清洁模式用独立的 `select` entity 更合适。**

---

## 四、Beatbot 全部 Entity 架构

```
设备: Beatbot 泳池清洁机器人 (ProductTypeEnum.POOL_ROBOT)
│
├── vacuum (主功能, name=None, supported_features=STATE|START|PAUSE|STOP|RETURN_HOME)
│   ├── activity 属性: WorkStatusEnum → VacuumActivity 映射
│   └── available 属性: 设备在线 → True
│
├── select: clean_mode (CONFIG)
│   ├── options: fast / surface / custom / standard / pro / cec / multi / ai / platform
│   └── WorkModeEnum: fast=0, surface=1, custom=2, standard=3, pro=4, cec=5, multi=6, ai=7, platform=8
│
├── sensor: battery (DIAGNOSTIC, device_class=battery, unit=%)
├── sensor: status (DIAGNOSTIC, device_class=ENUM, translation_key="work_status")
├── sensor: firmware (DIAGNOSTIC)
│
├── binary_sensor: charging (DIAGNOSTIC, device_class=battery_charging)
├── binary_sensor: online (DIAGNOSTIC, device_class=connectivity)
├── binary_sensor: error_wheel_stuck (DIAGNOSTIC, device_class=PROBLEM, entity_registry_enabled_default=False)
├── binary_sensor: error_brush_stuck (DIAGNOSTIC, device_class=PROBLEM, entity_registry_enabled_default=False)
├── binary_sensor: error_filter_blocked (DIAGNOSTIC, device_class=PROBLEM, entity_registry_enabled_default=False)
├── binary_sensor: error_water_sensor (DIAGNOSTIC, device_class=PROBLEM, entity_registry_enabled_default=False)
├── binary_sensor: error_motor_overheat (DIAGNOSTIC, device_class=PROBLEM, entity_registry_enabled_default=False)
├── binary_sensor: error_low_battery (DIAGNOSTIC, device_class=PROBLEM, entity_registry_enabled_default=False)
├── binary_sensor: error_communication (DIAGNOSTIC, device_class=PROBLEM, entity_registry_enabled_default=False)
│
├── button: dock (CONFIG, device_class=IDENTIFY)  ← 靠岸快捷按钮
│
└── update: firmware (CONFIG, device_class=FIRMWARE)
    ├── installed_version + latest_version
    └── supported_features: INSTALL | PROGRESS
```

所有 entity：
- 共享同一个 `device_info`
- `_attr_has_entity_name = True`
- `unique_id` 格式：`"{serial}_{key}"`

---

## 五、Entity Mapping Contract

**Entity Mapping Contract = 设备 API 原始数据 → HA entity 标准属性的翻译规则。**

每个 entity 只关心自己的映射，映射逻辑集中在一个 dict/方法里：

| HA Entity | 设备 API 字段 | 映射方式 | 输出 |
|-----------|-------------|---------|------|
| vacuum.activity | `error_code` + `work_status` (int) | error_code!=0 → ERROR，否则 STATUS_MAP dict | VacuumActivity 枚举 |
| sensor.status | `work_status` (int) | `WORK_STATUS_MAP` dict + ENUM options | ENUM 字符串值 |
| sensor.battery | `battery_level` (int) | 直接映射 | 百分比数值 |
| sensor.firmware | `firmware_version` (str) | 直接映射 | 版本字符串 |
| binary_sensor.online | `is_online` (bool) | 直接映射 | on/off |
| binary_sensor.charging | `is_charging` (bool) | 直接映射 | on/off |
| binary_sensor.error_* | `error_code` (int, 位掩码) | `error_code & bit` → bool | PROBLEM on/off |
| select.clean_mode | `work_mode` (int) | `MODE_MAP` dict | 字符串选项 |
| button.dock | — | 命令调用 | action |
| update.firmware | `firmware_version` + API | 版本比对 | 可安装/进度 |

**核心原则：**

1. **原始值 → HA 标准值**：int 码 → enum/string，bool → on/off
2. **每个 entity 只管自己的映射**——vacuum 不处理 battery，sensor 不处理 mode
3. **映射逻辑集中**：一个 dict 或一个方法，不要散落多处

---

## 六、API Schema

**API Schema = Beatbot API 返回的数据结构定义，是 Entity Mapping Contract 的上游输入。**

| API 字段 | 类型 | 含义 | 对应 Entity |
|----------|------|------|-------------|
| `serial` | str | 设备序列号 | unique_id 前缀 |
| `model` | str | 设备型号 | device_info.model |
| `work_status` | int | 工作状态码 (0-20) | vacuum.activity |
| `work_mode` | int | 清洁模式码 | select.clean_mode |
| `error_code` | int | 错误位掩码（bit0~bit6，每位=一种故障） | vacuum.activity + binary_sensor.error_* |
| `battery_level` | int | 电量百分比 | sensor.battery |
| `firmware_version` | str | 固件版本 | sensor.firmware + update.firmware |
| `is_online` | bool | 是否在线 | binary_sensor.online |
| `is_charging` | bool | 是否正在充电 | binary_sensor.charging |

```python
from dataclasses import dataclass

@dataclass
class BeatbotDeviceData:
    serial: str
    model: str
    work_status: int
    work_mode: int
    error_code: int
    battery_level: int
    firmware_version: str
    is_online: bool
    is_charging: bool
```

---