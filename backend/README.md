# FilmOS Backend

## development 排单助手

当前默认排单循环位于 `app/agent/scheduling.py`，通过 `SchedulingCapabilities`
调用三个受限工具：`read_board`、`read_draft`、`generate_draft`。模型拿到工具结果后继续回答。
图不依赖 ORM；进程内适配位于 `services/scheduling_agent_service.py`。
提示词集中在 `app/agent/prompt_templates/scheduling-v1.md`，最多六次模型决策。
聊天展示历史用于多轮上下文，生产确认不依赖模型或图内 interrupt。
`/api/schedule-plans/{id}` 提供草案读取/更新，`/{id}/apply` 绑定内容版本执行。
旧 `graph.py` 的 checkpoint 循环保留用于旧确认兼容；OpenClaw 不再是默认运行时。
录单继续走现有受控字段提取/订单表单，尚未迁入新的排单图。

FastAPI 后端，是系统的**唯一业务入口**：对外提供 REST API，内部承载业务逻辑、鉴权、AI Agent。前端只调这里，不直连数据库。

---

## 分层

```
HTTP 请求
   │
   ▼
Router 层   (app/routers/)    入参校验（Pydantic）+ JWT 鉴权 + 调用 Service
   │
   ▼
Service 层  (app/services/)   业务逻辑（订单状态流转、删除保护、配方快照…）
   │                          数据访问目前也在此层（用 SQLAlchemy）
   ▼
PostgreSQL  (app/models/)     SQLAlchemy 2.0 async ORM
```

``` mermaid
flowchart TD
    C["—— HTTP 编排层 ——<br/>routers/orders.py<br/>路由/依赖注入/鉴权/请求校验"]
    SC["schemas/order.py<br/>Pydantic 出入参校验"]
    SV["—— 业务逻辑层 ——<br/>services/order_service.py<br/>订单号生成/配方快照/状态流转"]
    M["models/order.py<br/>SQLAlchemy ORM 模型"]
    DB[("PostgreSQL")]

    C -->|"Depends(get_current_user)<br/>Depends(get_db)"| SV
    C -.校验.-> SC
    SV --> M --> DB
```

> `app/repositories/` 是预留的数据访问层目录，当前数据访问仍写在 Service 里；将来复杂度上来后可把查询下沉到 Repository。

领域划分：`Order`（订单）、`Production`（排产/看板）、`MasterData`（客户/产品/配方/机器/品类）、`Auth`（Casdoor 身份映射与 RBAC）、`Agent`（AI 对话）。

---

## 目录结构

```
app/
├── main.py            # FastAPI 应用装配 + lifespan（启动时初始化 Agent 图）
├── core/              # 配置、数据库、鉴权、日志等基础设施
│   ├── config.py      #   环境变量（Settings）
│   ├── database.py    #   async engine + session
│   ├── security.py    #   Casdoor JWT/JWKS 校验 + RBAC 依赖
│   ├── logging.py     #   structlog JSON 日志
│   └── phoenix.py     #   OpenInference/OTel → Phoenix（可选旁路）
├── models/            # SQLAlchemy 模型（含 audit、chat、user）
├── schemas/           # Pydantic 请求/响应模型
├── routers/           # API 路由（按领域拆分，全部 JWT 保护）
├── services/          # 业务逻辑 + 数据访问
├── repositories/      # （预留）数据访问层
└── agent/             # AI Agent runtime 适配与 LangGraph 回退实现
    ├── runtime/       #   OpenClaw Responses API 适配器
    ├── graph.py       #   StateGraph 定义 + Postgres checkpointer 生命周期
    ├── tools.py       #   工具 schema + 读/写工具执行
    ├── skills.py      #   意图路由（关键词）+ 受限工具集
    ├── prompts.py     #   system prompt + 技能提示词
    └── runner.py      #   驱动图 + SSE 事件 + 审计
```

---

## AI Agent runtime

浏览器始终调用 FastAPI；后端通过 `AGENT_RUNTIME` 选择运行时，并保持相同的 SSE 契约、PostgreSQL 展示历史和审计。

- `openclaw`：当前首选。后端通过私有容器网络调用 OpenClaw Responses API。会话用用户与 FilmOS session 共同派生的不可逆标识隔离。第一版只有文本对话，没有业务工具。
- `langgraph`：临时回退路径，保留原有对话式录单与排产能力。

OpenClaw 容器配置见 [../openclaw/README.md](../openclaw/README.md)。它的内部 SQLite 仅保存 Agent runtime 状态，不是业务数据库。

## LangGraph 回退实现

对话式录单与排产。要点：

- **图编排**：`agent`（调 LLM）→ `tools`（执行工具）循环，直到产出文字回复。
- **人在回路**：写操作（建单、执行排产）在 tools 节点 `interrupt()` 挂起，前端确认后 `Command(resume)` 才执行，取消则丢弃。
- **状态持久化**：用 **Postgres** checkpointer（`AsyncPostgresSaver`）保存图状态，按 `session_id` 隔离。
  > 用 Postgres 而非 Redis：`langgraph-checkpoint-redis` 需要 Redis Stack（RediSearch），而项目用的是原版 `redis:7`；Postgres 已在运行且 LangGraph 原生支持。注意它用 psycopg（DSN 为 `postgresql://`，非 `postgresql+asyncpg://`）。
- **审计**：每轮对话记录 prompt / 技能 / 工具 / token 消耗到 `agent_audit_logs`（成本管控 + 泄漏留痕）。
- **LLM**：通过 langchain-openai 调用 OpenAI-compatible 接口；默认配置为千问 `qwen3.7-plus`。
- **Trace**：OpenInference 自动观测 LangChain/LangGraph，通过 OTLP/HTTP 发送到 Phoenix；由 `PHOENIX_ENABLED` 控制。

会话历史存 `chat_messages` 表（供 UI 渲染），图执行状态存 checkpointer（供 interrupt 恢复）——两者分工。

### Phoenix 可观测性

`app/core/phoenix.py` 在后端启动时注册 LangChain 自动埋点，业务和 Agent 代码不直接依赖 Phoenix SDK。Docker Compose 默认启用并将 Trace 发送到 `http://phoenix:6006/v1/traces`，浏览器通过 http://localhost:6006 查看 `filmos-agent` 项目。

Phoenix 是可关闭的观测旁路：未启用时不连接采集端，初始化失败只写 `phoenix_init_failed` 日志，不应阻止 API 启动。它不替代 structlog、Sentry、PostgreSQL 业务审计或 LangGraph checkpointer。

Trace 可能包含 Prompt、模型回复和工具参数。当前 Compose 配置只适合本地或受信任内网；生产环境必须启用认证、API Key、TLS 和保留策略，并固定 Phoenix 镜像版本。

---

## 开发

```bash
# 依赖（本地开发）
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt

# 迁移
alembic upgrade head                      # 应用迁移
alembic revision --autogenerate -m "..."  # 生成迁移

# 测试（需要一个可连的 Postgres，会用 filmos_test 库）
pytest -q

# Lint
ruff check .

# 脚本
python scripts/seed_admin.py <email> <password>   # 创建/重置登录账号
python scripts/seed_demo.py [--reset]             # 灌入演示数据（仅测试用）
```

容器内跑同样命令加前缀 `docker compose exec backend ...`。

---

## 环境变量（`backend/.env`）

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | Postgres 连接串（`postgresql+asyncpg://…`） |
| `REDIS_URL` | Redis 连接串 |
| `AUTH_PROVIDER` | `local` 或 `casdoor`；生产强制为 `casdoor` |
| `AUTH_SECRET` | 仅本地开发 HS256 登录使用；生产业务 Token 不使用该密钥 |
| `CASDOOR_ISSUER` | 外部 OIDC issuer，必须与 Token `iss` 完全一致 |
| `CASDOOR_CLIENT_ID` | FilmOS OIDC client ID，同时作为 access token audience |
| `CASDOOR_JWKS_URL` | FastAPI 通过私网读取的 Casdoor JWKS 地址 |
| `CASDOOR_ORGANIZATION` | 允许的 Casdoor 组织；生产固定为 `filmos` |
| `AGENT_RUNTIME` | `openclaw` 或 `langgraph`；代码默认回退为 `langgraph`，Compose 显式使用 `openclaw` |
| `OPENCLAW_BASE_URL` | 私有 OpenClaw Gateway 地址 |
| `OPENCLAW_GATEWAY_TOKEN` | 后端访问 Gateway 的共享 Token，不得下发前端 |
| `OPENCLAW_AGENT_ID` | OpenClaw Agent ID，默认 `filmos-web` |
| `LLM_API_KEY` | Agent 的模型 API Key（空则 Agent 报错但不影响其余接口） |
| `LLM_BASE_URL` | OpenAI-compatible API 地址；默认千问国内 DashScope |
| `LLM_MODEL` | 模型 ID；默认 `qwen3.7-plus` |
| `LLM_VISION_MODEL` | JPG/PNG 订单识别模型；默认 `qwen3-vl-plus` |
| `LLM_REQUEST_TIMEOUT_SECONDS` | 受控订单提取模型调用超时；默认 60 秒 |
| `AGENT_IMAGE_MAX_BYTES` | 单张订单图片解码后的最大字节数；默认 5MB |
| `CHAT_ATTACHMENT_DIR` | 聊天图片附件目录；容器中固定为 `/app/data/chat-attachments` 并挂载私有持久卷 |
| `SENTRY_DSN` | 可选，错误追踪 |
| `PHOENIX_ENABLED` | 是否启用 Agent Trace；后端默认 `false`，Compose 当前设为 `true` |
| `PHOENIX_COLLECTOR_ENDPOINT` | Phoenix 根地址，默认 `http://phoenix:6006` |
| `PHOENIX_PROJECT_NAME` | Phoenix 项目名，默认 `filmos-agent` |

> Alembic 的 autogenerate 已配置忽略 LangGraph checkpointer 自建的表（`checkpoints` 等），不会误删。
