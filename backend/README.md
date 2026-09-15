# FilmOS Backend

> 后续AI助手重构统一遵循 [PRD](../meta/PRD.md) 及配套设计。下文描述当前实现，不能替代目标设计。

## 专用 Agent

录单和排单分别使用 `app/agent/specialized/` 内的独立 Graph；`registry.py` 固定配置与权限，`worker.py` 从 PostgreSQL 领取持久 Run。HTTP 接受返回 202，SSE 独立补读事件，确认 API 执行正式业务写入。旧混合聊天、历史读取、确认恢复和 checkpoint 运行时已删除。

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
├── main.py            # FastAPI 应用与路由装配
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
└── agent/             # 专用 Agent 执行
    ├── registry.py    #   图版本、可信上下文与权限
    ├── worker.py      #   Run 队列、租约、执行、终结
    └── specialized/   #   录单/排单 Graph、提示词与工具能力
```

---

## Agent 执行

浏览器通过同源 `/api/agent/v2` 代理调用后端。消息、Run 和接收事件原子入库；独立 Worker 按会话串行执行，图只读取数据和编辑草稿。录单创建与排单执行均由用户按钮携带最新版本明确确认。

### Phoenix 可观测性

`app/core/phoenix.py` 在后端启动时注册 LangChain 自动埋点，业务和 Agent 代码不直接依赖 Phoenix SDK。Docker Compose 默认启用并将 Trace 发送到 `http://phoenix:6006/v1/traces`，浏览器通过 http://localhost:6006 查看 `filmos-agent` 项目。

Phoenix 是可关闭的观测旁路：未启用时不连接采集端，初始化失败只写 `phoenix_init_failed` 日志，不应阻止 API 启动。它不替代 structlog、Sentry、PostgreSQL 业务审计。

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
| `LLM_API_KEY` | Agent 的模型 API Key（空则 Agent 报错但不影响其余接口） |
| `LLM_BASE_URL` | OpenAI-compatible API 地址；默认千问国内 DashScope |
| `LLM_MODEL` | 模型 ID；默认 `qwen3.7-plus` |
| `LLM_VISION_MODEL` | JPG/PNG 订单识别模型；默认 `qwen3-vl-plus` |
| `LLM_REQUEST_TIMEOUT_SECONDS` | 受控订单提取模型调用超时；默认 60 秒 |
| `CHAT_ATTACHMENT_DIR` | 聊天图片附件目录；容器中固定为 `/app/data/chat-attachments` 并挂载私有持久卷 |
| `SENTRY_DSN` | 可选，错误追踪 |
| `PHOENIX_ENABLED` | 是否启用 Agent Trace；后端默认 `false`，Compose 当前设为 `true` |
| `PHOENIX_COLLECTOR_ENDPOINT` | Phoenix 根地址，默认 `http://phoenix:6006` |
| `PHOENIX_PROJECT_NAME` | Phoenix 项目名，默认 `filmos-agent` |



### 专用 Agent（验收中）

新版提供录单和排单两个独立 Graph，使用 PostgreSQL 持久 Run 队列和独立 worker。HTTP 接受消息返回 202，SSE 只读取持久事件；业务确认仍由用户操作接口执行。默认 `AGENT_V2_ENABLED=true`，旧运行时已移除，实际状态与启用步骤见 [实施进度](../meta/agent-design/implementation-status.md)。

```bash
venv/bin/python -m pytest tests/test_agent_v2.py tests/test_order_intake_v2.py tests/test_scheduling_v2.py tests/test_agent_migrations.py -q
# 已配置独立验收环境并开启开关后
venv/bin/python -m app.agent.worker
```

迁移测试创建并删除 `filmos_migration_test_*` 临时数据库，不升级实际业务库。应用回退须保留扩展 Schema，不要 downgrade 删除已接受的任务。真实模型评测、业务联调、生产切换尚未验收。

截图上传的固定上限为 5MiB / 2000 万像素，由 `agent_attachment_service.py` 校验；旧 AGENT_IMAGE_MAX_BYTES 设置已移除。
