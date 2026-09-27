# FilmOS (ZM-OS)

> **development 分支**：AI助手重构设计已确认，开发依据见 [PRD](meta/PRD.md) 与 [ADR 0010](meta/decisions/0010-specialized-agent-sessions-and-durable-runs.md)。
> 下文介绍当前实现，不代表目标架构已落地；运行与发布说明见 [开发部署说明](deploy/production/DEVELOPMENT.md)。

塑料薄膜工厂的订单管理系统：把「微信收单 → 手工录 Excel → 白板排产」的流程，替换成一套带 AI 助手的 Web 系统——对话式录单、看板式排产、生产任务跟踪。

这是原 Next.js 全栈单体应用的重写版，转向 **Python 主导、前后端分离** 的架构，目标是贴近专业 SaaS 团队的工程实践（分层、鉴权、测试、CI/CD、可观测性、AI Agent）。

---

## 整体架构

前后端分离，单仓库（monorepo）管理多个独立容器：

``` mermaid
flowchart LR
    subgraph FE["前端 frontend (Next.js)"]
        UI["浏览器 UI<br/>看板/订单/对话"]
        NA["Auth.js<br/>OIDC 会话 + Token 刷新"]
    end
    subgraph BE["后端 backend (FastAPI) — 唯一业务入口"]
        MW["JWT 中间件"]
        R["Router 层"]
        S["Service 层"]
        AR["Agent runtime adapter"]
    end
    CD["Casdoor<br/>OIDC + 用户角色"]
    PG[("PostgreSQL<br/>业务/聊天历史/审计")]
    QW["千问<br/>OpenAI-compatible API"]
    LG["LangGraph<br/>受限排单循环"]
    PX["Phoenix<br/>可选 Trace UI"]

    UI -->|"REST + Bearer JWT"| MW
    UI -->|"SSE 流式对话"| MW
    UI -->|OIDC 跳转| CD
    CD -->|RS256 access token| NA --> UI
    MW --> R --> S --> PG
    R --> AR --> LG --> QW
    LG -->|受限能力接口| S
    LG -.->|"OpenInference / OTLP"| PX
```

关键点：

- **前端只做 UI**：不直连数据库，所有数据都经 FastAPI。这是把「前后端分离」落到实处的架构，也是大厂最常见的分工。
- **后端是唯一业务入口**：REST API + Agent 适配层，统一完成鉴权、用户会话隔离、PostgreSQL 历史持久化和 SSE 流式返回。
- **Casdoor 负责生产登录**：Auth.js 完成 OIDC code flow 和 Token 刷新，FastAPI 通过 JWKS 验证短期 RS256 access token，并把身份映射到稳定的本地用户 ID。
- **FastAPI 负责授权**：`OWNER` 与 `OPERATOR` 都可管理订单、生产任务和自己的 Agent 会话；只有 `OWNER` 可修改基础数据。
- **Agent** 在 FastAPI 进程内运行：录单由受控提取服务生成表单，排单由 LangGraph 调用只读与草案工具；业务写入必须明确确认。
- **PostgreSQL** 存业务数据、聊天历史和审计日志；Redis 目前不是核心依赖，只在本地 Compose 保留。
- **Phoenix** 通过 OpenInference/OpenTelemetry 接收 Agent Trace，用于查看模型、图节点和工具调用；它是可关闭的观测旁路，不参与业务事务。

---



## 仓库结构

```
.
├── frontend/            # Next.js 前端（UI 层）——详见 frontend/README.md
├── backend/             # FastAPI 后端（业务 + AI Agent）——详见 backend/README.md
├── deploy/production/   # 腾讯云单机 Compose、发布与备份脚本
├── docker-compose.yml   # 本地/staging 编排：frontend + backend + postgres + redis + phoenix
├── meta/                # Ground Truth、工程规范、测试要求和架构决策
└── .github/workflows/   # CI：backend-ci（lint+test+build）、frontend-ci（lint+typecheck+build）
```

细节文档下沉到各自子目录，避免根文档随实现频繁变动：

- 前端细节 → [frontend/README.md](frontend/README.md)
- 后端细节 → [backend/README.md](backend/README.md)
- 项目规范 → [meta/README.md](meta/README.md)

---



## 技术栈


| 层        | 技术                                                              |
| -------- | --------------------------------------------------------------- |
| 前端       | Next.js (App Router) · React · TypeScript · Tailwind · Auth.js |
| 后端       | FastAPI · SQLAlchemy 2.0 (async) · Alembic · Pydantic           |
| AI Agent | LangGraph· OpenAI-compatible API（默认千问）        |
| Agent 可观测性 | OpenInference · OpenTelemetry · Arize Phoenix |
| 身份       | Casdoor · OIDC · RS256/JWKS                                    |
| 数据库      | PostgreSQL · Redis（仅本地可选）                                  |
| 部署       | Docker Compose                                                  |
| CI       | GitHub Actions                                                  |


---



## 本地运行

前置：Docker（守护进程需运行）。

```bash
# 1. 启动全部服务（首次或改了代码用 --build）
docker compose up -d --build

# 2. 建表（首次或有新迁移时）
docker compose exec backend alembic upgrade head

# 3. 创建本地开发账号（生产环境改用 Casdoor）
docker compose exec backend python scripts/seed_admin.py owner@filmos.local filmos123

# 4.（可选）灌入演示数据，方便测试看板/排产/Agent
docker compose exec backend python scripts/seed_demo.py
```

打开 [http://localhost:3000，用上面的账号登录。](http://localhost:3000，用上面的账号登录。)

各服务端口：前端 `3000`、后端 `8000`（API 文档 `/docs`）、Phoenix `6006`（Trace UI）、Postgres `5432`、Redis `6379`。

Docker Compose 默认启用 Phoenix。发起一次 AI 对话后，可打开 http://localhost:6006，在 `filmos-agent` 项目中查看 Trace。Phoenix 不可用时不会影响普通业务 API。

### 需要自己配置的凭证

以下能力代码已接好，但需要你提供凭证才生效（不提供也不影响其余功能）：

- **AI Agent 对话**：在 `backend/.env` 配置 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`；图片识别使用 `LLM_VISION_MODEL`。
- **错误追踪（可选）**：设 `SENTRY_DSN` 启用 Sentry

### Phoenix 安全说明

当前 Compose 配置面向本地或受信任内网，Phoenix UI 未开启认证。生产环境必须启用认证和访问控制、设置 Trace 保留期并固定 Phoenix 镜像版本；Prompt、回复和工具参数都可能进入 Trace。

---

## 生产部署

根目录 `docker-compose.yml` 仅用于本地开发，不应直接部署到公网。腾讯云轻量服务器使用独立生产栈，包含 PostgreSQL、Casdoor、FastAPI、Next.js与 Caddy。Casdoor 使用独立数据库和数据库账号；初期不包含 Redis、Phoenix、Sentry 或 COS。ICP备案通过前只允许 SSH 隧道访问。

完整安装、更新、备份、恢复、回滚和备案后启用 HTTPS 的步骤见 [deploy/production/README.md](deploy/production/README.md)。

---



## 状态

前后端核心业务、鉴权、可观测性、CI/CD、AI Agent 均已完成。演示数据脚本仅用于本地测试，不进生产。

## 部署一致性检查

本地 Casdoor 启动、AI 参数对照、版本报告与真实识别验收见 [运维流程](deploy/OPERATIONS.md)。
生产发布会记录运行证据并执行一次合成图片模型验收；容器健康不代表浏览器业务验收完成。
