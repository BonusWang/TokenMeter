# TokenMeter 2.0：Codex 订阅额度规划

## 产品目标

TokenMeter 2.0 对齐 [CodexBar](https://github.com/steipete/CodexBar) 的核心体验：显示 AI 编程订阅的真实限额窗口，而不把订阅误当成按量 API 账单。

- 首期只保留 Codex、DeepSeek 和 Xiaomi MiMo，主面板一键切换。
- Codex 展示已用/剩余百分比、当前周额度、重置倒计时、套餐和 Credits，右侧只显示近 7 天 Token 使用量，不显示金额。
- API 计费 Provider 保留余额、金额、Token、分时图和年度活动，不用统一金额模板套用所有模型。
- 悬浮球跟随 Provider 动态切换：Codex 用深浅主题水位和倒计时显示周额度，API 平台显示今日金额和余额。
- 数据不足时显示未知或错误，不用公开价格反推“伪额度”。

## 数据能力矩阵

| Provider | 认证来源 | 主要展示 | 当前实现 |
| --- | --- | --- | --- |
| Codex | 本机 Codex CLI `auth.json` | 周额度、专项窗口、近 7 天及年度 Token 活动、套餐 | 已实现 |
| DeepSeek | 现有 API Key/控制台凭据 | 余额、Token、费用和历史活动 | 保留兼容 |
| Xiaomi MiMo | 现有控制台凭据 | 余额、Token、费用和历史活动 | 保留兼容 |

Codex 额度语义参考 [CodexBar Codex Provider](https://github.com/steipete/CodexBar/blob/main/docs/codex.md)。

## 已执行的 2.0 基础批次

本批次已经完成以下代码能力，但在正式准备 2.0 Tag/Release 前不提前修改公开版本号：

- 增加通用 `ProviderQuota`、`QuotaWindow` 和 `QuotaMetric` 数据结构。
- Provider 注册表收缩为 DeepSeek、MiMo、Codex，继续复用现有连接测试、快照隔离和错误状态。
- Codex 读取本机 OAuth 登录，查询主窗口、次窗口、专项限额与 Credits。
- Codex 只解析本机 `sessions/**/*.jsonl` 中的时间戳和 `token_count` 事件，生成年度活动热力图及五项本地统计，不读取或上传对话正文。
- 顶栏保留一个 Provider 下拉框，切换后立即清空旧范围并刷新，避免跨 Provider 短暂错标。
- 主面板、统计区和悬浮球根据 Provider 能力自动切换“订阅额度”或“API 账单”视图。
- Codex 左侧额度卡展示已用/剩余比例和重置倒计时，右侧展示近 7 天 Token 使用量；套餐、账号和附加额度动态填充。

## 数据源与安全边界

CodexBar 的这类能力依赖本机 CLI OAuth 会话和产品内部额度端点，并不等同于 OpenAI Admin API。TokenMeter 只读取用户已经登录的本机凭据文件，不采集密码。

内部额度端点可能随产品更新而变化，因此每个 Provider 独立解析、独立报错。认证失败不会回退到估算数据，也不会把上一个账号或 Provider 的缓存重新标成当前额度。

当前基础批次还有这些明确限制：

- Codex 尚未加入 `codex app-server` JSON-RPC 回退和 OAuth 自动刷新。
- 本地统计以现有 Codex JSONL 为准；已删除或不在 `CODEX_HOME` 中的会话不会被计入。

## 后续发布批次

### 2.0 Beta：认证韧性

- Codex 增加 app-server 读取回退，并在不扩大权限的前提下刷新 OAuth。
- 连接设置显示 Codex 凭据来源、读取路径和最后错误，不要求用户猜测该填哪种 Key。

### 2.0 RC：多账号与交互

- 为同一 Provider 增加账号配置和快捷切换；快照按 `provider + account` 隔离。
- 增加“剩余/已用”展示偏好、重置通知阈值和临近重置提醒。
- 对 Codex 专项额度提供折叠，不在标题栏增加第二个模型筛选器。
- 补齐离线状态、凭据过期、接口结构变化和账号迁移的 UI 回归验证。

### 2.0 Stable：发布与迁移

- 完成凭据日志审计、升级/回滚、安装包和 Windows 桌面视觉验证。
- 将现有兼容金额字段迁移为带币种的金额对象，但保持旧配置和 SQLite 数据可读。
- 正式发布时统一更新版本号、多语言 README、发布说明和 Provider 连接指南。

## 搜索增长与内容结构

首期搜索入口只对应已经实现的能力：`Codex usage limits`、`Codex 5-hour limit`、`Codex weekly usage`、`DeepSeek usage` 和 `MiMo token usage`。Codex 页面说明 OAuth、额度窗口、重置时间、本地年度活动与隐私边界；DeepSeek/MiMo 继续使用 API usage、cost 和 balance 语义。
