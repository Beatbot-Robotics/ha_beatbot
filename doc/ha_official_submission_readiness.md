# Home Assistant 官方集成提交准备度

最后更新：2026-07-02

## 当前结论

当前项目还不具备向 Home Assistant Core 提交新集成 PR 的条件。

功能主体已经成形，但生产配置、Core manifest、Bronze 质量等级、测试和官方文档等仍有硬阻塞项。当前完成度粗略估计为 **55%–65%**。

> 本文档按 Home Assistant 2026 年的新集成要求维护。新集成至少需要达到 Integration Quality Scale 的 Bronze 等级。

## P0：提交前必须完成

### 1. 切换到生产 OAuth 和 API

当前状态：

- `OAUTH2_AUTHORIZE_URL` / `OAUTH2_TOKEN_URL` 为正式 HTTPS 地址（`oauth-test.beatbot.com`，命名带 `-test` 但即生产域）。
- `REGION_API_BASE_URL` 的 `cn`/`na`/`eu` 均为生产域（`*-iot-test.beatbot.com`，即生产）。
- `DEV_MODE` 已删除，仓库不存在 `localhost` / `host.docker.internal` / 开发地址。
- 缺失或未知 region 在 config flow 阶段 `async_abort(reason="unknown_region")`，API client 构造时再次 `raise ValueError`，无任何回退。
- OAuth client `home-assistant` 已在 Beatbot OAuth 服务端登记，redirect URI 为 `https://my.home-assistant.io/redirect/oauth`，强制 PKCE，scope `device:info`，grant types `authorization_code,refresh_token`。
- access token TTL 由 60s 调整为 7200s（2h），refresh token TTL 15 天且 `reuse-refresh-tokens: false`。

涉及文件：

- `custom_components/beatbot/iot/const.py`
- `custom_components/beatbot/api.py`
- `custom_components/beatbot/config_flow.py`

验收标准：

- [x] OAuth authorize/token 地址均为正式 HTTPS 地址。
- [x] `DEV_MODE` 和本地开发地址不进入生产代码路径。
- [x] `cn`、`na`、`eu` 均完成真实账号联调。
- [x] 缺失或未知 region 时明确报错，不回退到开发环境。
- [x] OAuth redirect URI 与 Beatbot OAuth 服务端登记值一致。
- [x] REST API 和 WebSocket 均使用有效 TLS 证书（生产 HTTPS/WSS 域）。

### 2. 将 manifest 转换为 Core 格式

当前 `manifest.json` 仍是 custom integration 格式。

需要处理：

- [ ] 删除 `version`。
- [ ] 删除 `requires_home_assistant`。
- [ ] 删除 `issue_tracker`。
- [ ] 将 `documentation` 改为：
  `https://www.home-assistant.io/integrations/beatbot`
- [ ] 删除集成自身的 `loggers`，仅在确有外部库 logger 时声明。
- [ ] 将第三方依赖精确锁定到 `==` 版本，或移除不必要的依赖。
- [ ] Bronze 全部通过后添加 `"quality_scale": "bronze"`。
- [ ] 最终确认 `integration_type` 使用 `hub` 是否准确。
- [ ] 最终确认 `iot_class` 使用 `cloud_push` 是否准确。

特别注意：

当前依赖为 `PyJWT>=2.0`，不符合 Core 对依赖精确锁定的要求。应评估是否可以在不依赖 PyJWT 的情况下读取 JWT payload；如果保留 PyJWT，则必须使用官方 Core 当前允许的精确版本。

### 3. 补齐字符串源文件

当前只有：

- `strings.json`（英文源字符串）
- `translations/en.json`
- `translations/zh-Hans.json`

需要处理：

- [x] 添加 `custom_components/beatbot/strings.json`，作为英文源字符串。
- [x] 确保 entity、config flow、异常信息的 translation key 与源文件一致。
- [ ] 通过 Home Assistant translation 和 hassfest 校验。
- [x] 不在 Python 中新增面向用户的硬编码英文错误消息。

### 4. 达到 Bronze 质量等级

需要新增 `custom_components/beatbot/quality_scale.yaml`，逐项记录规则状态。

当前明确需要完成的 Bronze 项：

- [ ] `config_flow`：只能通过 UI 配置。
- [ ] `config_flow_test_coverage`：config flow 所有路径有测试。
- [ ] `test_before_configure`：创建 config entry 前验证账号/API 可用。
- [ ] `test_before_setup`：初始化时验证连接，失败时正确抛出 HA 异常。
- [ ] `unique_config_entry`：同一 Beatbot 账号不能重复配置。
- [ ] `runtime_data`：使用 `ConfigEntry.runtime_data`，不再用 `hass.data` 保存入口运行时对象。
- [ ] `entity_unique_id`：所有实体都有稳定 unique ID。
- [ ] `has_entity_name`：所有实体使用 `has_entity_name = True`。
- [ ] `entity_event_setup`：WebSocket 事件在正确生命周期启动和停止。
- [ ] `appropriate_polling`：说明 30 秒兜底轮询的合理性。
- [ ] `common_modules`：共享逻辑放在公共模块。
- [ ] `dependency_transparency`：明确外部库来源和维护方式。
- [ ] `brands`：提供官方品牌资源。
- [ ] `docs_high_level_description`：官方文档包含集成简介。
- [ ] `docs_installation_instructions`：提供逐步安装说明。
- [ ] `docs_removal_instructions`：提供删除集成说明。

重点重构：

```python
type BeatbotConfigEntry = ConfigEntry[BeatbotRuntimeData]
```

建议使用 dataclass 保存以下运行时对象：

- coordinator
- API client
- OAuth2 session
- event client

各平台通过 `entry.runtime_data` 获取，不再访问：

```python
hass.data[DOMAIN][entry.entry_id]
```

### 5. 补齐 Core 级自动化测试

现有测试覆盖了部分 entity、coordinator、config flow 和 WebSocket 逻辑，但还不足以证明集成达到 Bronze。

必须补充：

- [ ] `async_setup_entry` 成功。
- [ ] 首次连接失败触发 `ConfigEntryNotReady`。
- [ ] 首次认证失败触发 `ConfigEntryAuthFailed`。
- [ ] `async_unload_entry` 停止 WebSocket、取消任务并卸载平台。
- [ ] binary sensor、sensor、select、vacuum 的平台 setup 和实体创建。
- [ ] 设备动态新增后实体能被添加。
- [ ] 所有 API 方法的成功响应。
- [ ] HTTP 401/403、4xx/5xx、超时、连接失败、非法 JSON、业务错误码。
- [ ] OAuth 成功、拒绝、超时、无效 token、缺少 `sub`、重复账号。
- [ ] reauth 成功和账号不一致。
- [ ] WebSocket 握手、断线重连、token 刷新、关闭码、卸载竞态。
- [ ] 推送增量状态与定时全量刷新之间的一致性。
- [ ] 不支持的型号和分类不会创建实体。
- [ ] entity registry 迁移/清理逻辑。
- [ ] 测试覆盖率满足目标等级。

最终测试必须迁入 Home Assistant Core：

```text
tests/components/beatbot/
```

不能只以 `pytest-homeassistant-custom-component` 的结果作为官方提交验收。

### 6. 迁入 Home Assistant Core 仓库验证

正式提交时需要将代码放到：

```text
homeassistant/components/beatbot/
tests/components/beatbot/
```

验收标准：

- [ ] 在 Core 当前开发分支运行目标集成测试。
- [ ] 通过 Ruff。
- [ ] 通过 mypy。
- [ ] 通过 hassfest。
- [ ] 通过 manifest、translations 和 quality scale 校验。
- [ ] 无新增未处理警告。
- [ ] PR 只包含该集成所需变更，避免大规模无关代码。

## P1：预计会在评审中被要求处理

### Domain 与命名

- [x] 最终 domain 定为 `beatbot`。
- [ ] 检查 domain 在 Core、Brands、文档仓库中均未被占用。
- [x] 展示名定为 `Beatbot`。

Domain 合入后不可随意修改，因此需要在提交前定稿。

### 异常处理

- [ ] 缩小 `except Exception` 的捕获范围。
- [ ] 不把编程错误统一转换为网络错误。
- [ ] 确保取消任务时 `CancelledError` 能正常传播。
- [ ] 控制命令失败使用可翻译的 `HomeAssistantError`。

### WebSocket 稳定性

- [ ] 断线只记录一次，恢复连接记录一次，避免循环刷 warning。
- [ ] 明确关闭码 `4001`、`4002`、`4003` 的服务端契约。
- [ ] 验证多 HA 实例登录时 `4002` 的实际用户体验。
- [ ] 增加连接超时和长期不可达测试。
- [ ] 明确推送失效时轮询是否能完整恢复状态。
- [ ] 对齐长连接 token 过期契约：access token TTL 已调为 7200s，需确认 WS 连接存活超过 2h 后服务端用约定关闭码（如 `4001`）断开，客户端用新 token 重连；不再依赖 60s 短 TTL 的隐式刷新。

### Entity 与设备模型

- [ ] 为每个平台设置合适的 `PARALLEL_UPDATES`。
- [ ] 验证 device identifier 在账号之间不会冲突。
- [ ] 验证型号、名称、固件版本和 manufacturer 信息准确。
- [ ] 验证 enum state、device class、entity category 均符合 HA 语义。
- [ ] 低价值或噪声实体考虑默认禁用。
- [ ] 设备移除后是否清理 stale device，至少形成明确策略。

### 代码清理

- [ ] 删除 `const.py` 中未使用的旧配置和常量。
- [ ] 清除开发注释、内部网关实现细节和本地环境地址。
- [ ] 完善公共 API 类型注解。
- [ ] 对外部 API payload 进行严格结构验证。
- [ ] 统一代码格式和 import 顺序。

## 官方提交涉及的三个仓库

### 1. Home Assistant Core

内容：

- 集成代码
- Core 测试
- `manifest.json`
- `strings.json`
- `quality_scale.yaml`

目标仓库：

- <https://github.com/home-assistant/core>

### 2. Home Assistant 文档

需要新增：

```text
source/_integrations/beatbot.markdown
```

至少包含：

- [ ] Beatbot 和该集成的简介。
- [ ] 支持地区。
- [ ] 支持型号和不支持型号。
- [ ] 安装前置条件。
- [ ] OAuth 授权步骤。
- [ ] 创建的设备与实体。
- [ ] 控制功能。
- [ ] 数据通过 WebSocket 推送、30 秒轮询兜底。
- [ ] 已知限制。
- [ ] 故障排查。
- [ ] 删除集成的方法。

目标仓库：

- <https://github.com/home-assistant/home-assistant.io>

### 3. Home Assistant Brands

需要为 `beatbot` 提供符合要求的：

- [ ] icon
- [ ] logo
- [ ] 必要时提供深色版本

目标仓库：

- <https://github.com/home-assistant/brands>

## 推荐实施顺序

1. 确定最终 domain 和生产 OAuth/API 契约。
2. 完成三个区域的生产联调。
3. 将运行时数据迁移到 `ConfigEntry.runtime_data`。
4. 修正 manifest，新增 `strings.json` 和 `quality_scale.yaml`。
5. 补齐 setup、API、平台和 WebSocket 测试。
6. 将代码复制到 Home Assistant Core fork 中适配并运行完整 CI。
7. 同步准备官方集成文档和 Brands 资源。
8. 先提交 Brands 和文档 PR，或按 Core reviewer 要求关联三个 PR。
9. 提交 Core PR，并逐项响应 reviewer 意见。

## 提交前最终验收

- [x] 仓库不存在 `localhost`、`host.docker.internal` 或开发 API 地址。
- [x] 仓库不存在启用状态的 `DEV_MODE`。
- [x] 所有生产端点使用 HTTPS/WSS。
- [ ] 工作区干净，全部变更已提交。
- [ ] Core 目标测试全部通过。
- [ ] Ruff、mypy、hassfest 全部通过。
- [ ] Bronze checklist 全部完成或有官方允许的 exemption。
- [ ] OAuth 服务端已允许 Home Assistant 正式 redirect URI。
- [ ] Beatbot 后端具备稳定性、限流和可维护承诺。
- [ ] Code owner GitHub 账号有效并愿意持续处理 Issue/PR。
- [ ] Core、Docs、Brands 三个 PR 相互链接。

## 参考资料

- [Integration manifest](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
- [Integration Quality Scale rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/)
- [Checklist for creating a component](https://developers.home-assistant.io/docs/creating_component_code_review/)
- [Adding an integration page](https://developers.home-assistant.io/docs/documenting/create-page/)
- [Submit your work](https://developers.home-assistant.io/docs/development_submitting/)
