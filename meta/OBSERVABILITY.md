# FilmOS 可观测性

状态：Normative

本文件定义 FilmOS 中日志、错误追踪、AI Trace 和业务审计的职责边界，避免把不同用途的数据混在一个系统中。

## 1. 能力分工

| 能力 | 当前实现 | 主要用途 | 不是用来做什么 |
| --- | --- | --- | --- |
| 运行日志 | structlog JSON → stdout → Docker logs | 请求状态、耗时、启动事件、运行错误 | 长期业务审计 |
| 错误追踪 | Sentry（配置 DSN 后启用） | 异常聚合、堆栈、前后端性能 | Agent 执行链路分析 |
| AI Trace | OpenInference / OpenTelemetry → Phoenix | 模型调用、LangGraph/LangChain 步骤、工具调用和耗时 | 业务数据库、普通日志聚合 |
| 业务审计 | PostgreSQL 审计表 | 谁在何时执行了什么业务操作 | 调试堆栈和模型 Trace |

这些能力可以通过 request ID、session ID 或用户标识关联，但不能相互替代。

## 2. Phoenix 数据流

```text
LangChain / LangGraph
        │ OpenInference 自动埋点
        ▼
OpenTelemetry TracerProvider
        │ OTLP/HTTP /v1/traces
        ▼
Phoenix :6006
        │
        ├── Web UI / Trace 查询
        └── phoenixdata 独立持久卷
```

后端在 `app/core/phoenix.py` 中统一注册埋点。Agent 和业务 Service 不应直接导入 Phoenix SDK。

## 3. 当前配置

后端配置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PHOENIX_ENABLED` | `false` | 是否注册并导出 Agent Trace |
| `PHOENIX_COLLECTOR_ENDPOINT` | `http://phoenix:6006` | Phoenix 服务根地址；代码追加 `/v1/traces` |
| `PHOENIX_PROJECT_NAME` | `filmos-agent` | Phoenix 中的项目名称 |

Docker Compose 当前会：

- 启动 `arizephoenix/phoenix` 容器；
- 在宿主机开放 `http://localhost:6006`；
- 将后端的 `PHOENIX_ENABLED` 设置为 `true`；
- 使用 `phoenixdata` 保存 Phoenix 自身数据；
- 使用 `PHOENIX_WORKING_DIR=/mnt/data` 指向持久卷。

直接在 Compose 外运行后端时，Phoenix 默认关闭，除非显式设置 `PHOENIX_ENABLED=true`。

## 4. 失败行为

- `PHOENIX_ENABLED=false` 时不注册埋点、不连接采集端。
- 初始化异常只记录 `phoenix_init_failed`，不能阻止 FastAPI 启动。
- Phoenix 停止或网络不可达时，业务请求不得依赖 Trace 是否成功写入。
- Phoenix 不参与订单、排产、确认流程或数据库事务。
- 可观测性失败可以造成 Trace 缺失，但不能改变业务结果。

## 5. 本地使用

启动服务：

```bash
docker compose up -d --build phoenix backend frontend
```

打开 Phoenix UI：

```text
http://localhost:6006
```

默认项目名：

```text
filmos-agent
```

检查后端初始化日志：

```bash
docker compose logs --tail=100 backend
```

预期看到 `phoenix_enabled`；关闭时应看到 `phoenix_disabled`，初始化失败时会看到 `phoenix_init_failed`。

## 6. 数据安全

OpenInference Trace 可能采集：

- 用户 Prompt；
- 模型输入与回复；
- 工具名称、参数和结果；
- Token 使用量、耗时和错误；
- 会话相关元数据。

因此：

- 不得在 Prompt 或工具参数中注入密码、Token、Cookie、API Key 或数据库凭证；
- Phoenix UI 默认只适用于受信任的本地或内网环境；
- 生产环境必须启用 Phoenix 认证并为导出端配置 API Key，或通过受保护的反向代理/私网访问；
- 生产环境应使用 TLS，并限制只有必要人员可以查看 Trace；
- 必须明确 Trace 保留期。Phoenix 默认保留策略可能是无限期，不应无意识长期保存客户数据；
- 删除 FilmOS 业务数据不会自动删除 Phoenix 中已经采集的 Trace，两者需要分别治理。

## 7. 生产部署要求

- Docker 镜像必须固定明确版本，不能长期使用 `latest`；
- Phoenix 数据必须使用持久存储并纳入容量监控和备份策略评估；
- 设置明确的 `PHOENIX_DEFAULT_RETENTION_POLICY_DAYS` 或项目级保留策略；
- 开启认证时安全保存 `PHOENIX_SECRET`、管理员初始密码和 `PHOENIX_API_KEY`；
- UI 不得无认证暴露到公网；
- Phoenix 应保持可选旁路，不能成为后端健康检查通过的必要条件；
- 升级 Phoenix 或 OpenInference 依赖前，必须验证 Trace 兼容性和后端失败降级行为。

## 8. 与日志和 Sentry 的关系

- 查某次 HTTP 请求是否成功、耗时多少：先看结构化运行日志；
- 查 Python/Next.js 异常堆栈：看 Sentry；
- 查 Agent 为什么调用某个工具、模型每一步耗时：看 Phoenix；
- 查谁创建、移动或删除了订单：看业务审计表。

不要为了减少系统数量而把以上四类数据合并成一个不清晰的数据源。


## 9. 专用 Agent Worker

worker 启动时独立初始化结构化日志与可选 Phoenix。新版 Trace 强制隐藏 inputs、outputs 和图片，保留步骤/时延/token 等元信息；API 服务与 worker 的健康独立。worker 致命错误只记录异常类型，避免原始数据库/供应商异常正文进入日志。单轮失败记录 agent_run_failed 和 run_id：已知分类错误记录安全的 error_code，未知异常只记录 error_type；不记录模型原文或异常正文。

`python -m app.agent.worker --healthcheck` 检查 watchdog 最近 30 秒内是否完成数据库和附件清理检查。Compose 预留 190 秒正常关闭时间；进程失联仍由租约及重启后的 watchdog 回收 Run。新业务审计只记录结果摘要，统计不完整的 token 数为 NULL。

## 视觉识别诊断（2026-09-13）

视觉传输与Schema错误通过既有 `run.progress` 的 RECOGNITION_ERROR 阶段记录安全错误码与重试序号；终止时工作项 last_error_code 与 recognition.failed 保存原因。客户/产品选择通过 MATCHING 阶段和 context_snapshot.entity_matching 保存每单、每字段的接受/拒绝码。错误码协议见 [Agent contracts](agent-design/contracts.md)。禁止把图片字节、完整模型响应、上游HTTP响应正文或凭证放入诊断事件/异常；仅在受权限保护的业务提取记录保留核对所需原文与建议依据。

`/health` 的 revision 来自构建镜像；部署完成时输出相同的版本标记。发布不生成自动对照报告，不调用真实模型。
排查时按需查看容器健康和经过脱敏的运行日志，不输出环境全量、凭证或业务数据。操作见 [生产部署](../deploy/production/README.md)。

截图识别的结构校验失败通过 Worker 的 `recognition_error` 日志和
`RECOGNITION_ERROR` 事件记录 `run_id`、尝试次数、最多八个字段路径与校验类型。
未知字段名脱敏为 `<unknown>`，不记录字段值、模型正文、校验上下文或图片。
同一 Run 已写入的 `recognition.failed` 保留原始错误码，不由通用终止错误覆盖；
重试 Run 独立记录自己的失败。历史事件不能还原当时未记录的字段诊断。
