# FilmOS Backend

> 当前运行架构与本地启动入口见 [根 README](../README.md)；业务与设计约束见 [PRD](../meta/PRD.md)。

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

数据访问位于 Service 层；当前没有单独的 Repository 层。

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
│   └── scheduling/    # 排产：inputs 查询/指纹、planner 计算、service 用例/事务
└── agent/             # 专用 Agent 执行
    ├── registry.py    #   图版本、可信上下文与权限
    ├── worker.py      #   Run 队列、租约、执行、终结
    └── specialized/   #   录单/排单 Graph、提示词与工具能力
```

---

维护脚本位于 `scripts/maintenance/`，旧识别格式转换已移出 `app/`。实时识别仅处理 `OrderExtraction` v2；历史证据保留不变。定向数量修复在后端目录执行：

```bash
python -m scripts.maintenance.repair_intake_quantities --help
```

默认 dry-run；应用修复必须明确提供工作项 ID、`--apply` 和新备份文件。不得作为启动步骤自动执行。

`Dockerfile` 共用依赖与代码层，`local` target 保留本地卷访问方式，`production` target 使用专用非 root 用户及代理配置；API 和 Worker 共用镜像。

## Agent 执行

浏览器通过同源 `/api/agent/v2` 代理调用后端。消息、Run 和接收事件原子入库；独立 Worker 按会话串行执行，图只读取数据和编辑草稿。录单创建与排单执行均由用户按钮携带最新版本明确确认。

### Phoenix 可观测性

`app/core/phoenix.py` 提供可选埋点。默认本地和生产配置均关闭追踪，不启动 Phoenix。
本地使用 `./deploy/local/up.sh --phoenix`（从仓库根目录）时，独立 Worker 启用 LangChain/LangGraph 埋点，发送到 `http://phoenix:6006/v1/traces`；浏览器通过 http://localhost:6006 查看 `filmos-agent` 项目。

Worker 隐藏输入、输出和图片；采集器不参与业务事务，也不是 API/Worker 的启动依赖。
初始化失败只记录安全错误，不能阻止业务执行。生产启用追踪前的访问控制、保留策略与版本要求见 [可观测性说明](../meta/OBSERVABILITY.md)。

---

## 开发

```bash
# 依赖（本地开发）
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt -c requirements.lock

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

容器内跑同样命令加前缀 `docker compose --env-file deploy/local/.env -f deploy/local/docker-compose.yml exec backend ...`。

---

## 后端运行时变量

本地配置来源是 `deploy/local/.env`；数据库地址、运行环境和登录模式由 Compose 配置，模型与日志参数从该文件读取。下表说明运行时变量，不代表每项都需要手动填写。

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | Postgres 连接串（`postgresql+asyncpg://…`） |
| `AUTH_PROVIDER` | `local` 或 `casdoor`；生产强制为 `casdoor` |
| `AUTH_SECRET` | 仅本地开发 HS256 登录使用；生产业务 Token 不使用该密钥 |
| `CASDOOR_ISSUER` | 外部 OIDC issuer，必须与 Token `iss` 完全一致 |
| `CASDOOR_CLIENT_ID` | FilmOS OIDC client ID，同时作为 access token audience |
| `CASDOOR_JWKS_URL` | FastAPI 通过私网读取的 Casdoor JWKS 地址 |
| `CASDOOR_ORGANIZATION` | 允许的 Casdoor 组织；生产固定为 `filmos` |
| `LLM_API_KEY` | Agent 的模型 API Key（空则 Agent 报错但不影响其余接口） |
| `LLM_BASE_URL` | OpenAI-compatible API 地址；默认千问国内 DashScope |
| `LLM_MODEL` | 模型 ID；默认 `deepseek-v4-flash` |
| `LLM_VISION_MODEL` | JPG/PNG 订单识别模型；默认 `deepseek-flash` |
| `LLM_REQUEST_TIMEOUT_SECONDS` | 受控订单提取模型调用超时；默认 60 秒 |
| `CHAT_ATTACHMENT_DIR` | 聊天图片附件目录；容器中固定为 `/app/data/chat-attachments` 并挂载私有持久卷 |
| `SENTRY_DSN` | 可选，错误追踪 |
| `PHOENIX_ENABLED` | 是否启用 Agent Trace；默认 `false`，本地 Phoenix 扩展只为 Worker 开启 |
| `PHOENIX_COLLECTOR_ENDPOINT` | Phoenix 根地址，默认 `http://phoenix:6006` |
| `PHOENIX_PROJECT_NAME` | Phoenix 项目名，默认 `filmos-agent` |



### 专用 Agent 验证

默认 `AGENT_V2_ENABLED=true`；该开关用于维护停用，关闭不会恢复旧运行时。历史实施与验收记录见 [实施进度](../meta/agent-design/implementation-status.md)。

```bash
venv/bin/python -m pytest tests/test_agent_v2.py tests/test_order_intake_v2.py tests/test_scheduling_v2.py tests/test_agent_migrations.py -q
# 已配置独立验收环境并开启开关后
venv/bin/python -m app.agent.worker
```

迁移测试创建并删除 `filmos_migration_test_*` 临时数据库，不升级实际业务库。应用回退须保留扩展 Schema，不要 downgrade 删除已接受的任务。测试结果不能替代当前部署的登录、真实模型和业务样本验收。

截图上传的固定上限为 5MiB / 2000 万像素，由 `agent_attachment_service.py` 校验；旧 AGENT_IMAGE_MAX_BYTES 设置已移除。

Docker 本地部署统一读取仓库根目录下的 `deploy/local/.env`，生产读取 `deploy/production/.env.production`。直接在宿主机运行开发进程时，需要将对应配置显式注入进程；框架不会自动读取部署目录。后端数据库地址需使用宿主机地址，前端 `BACKEND_INTERNAL_URL` 也需指向宿主机后端。
