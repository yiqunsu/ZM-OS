# FilmOS (ZM-OS)

塑料薄膜工厂的订单管理系统：把「微信收单 → 手工录 Excel → 白板排产」的流程，替换成一套带 AI 助手的 Web 系统——对话式录单、看板式排产、生产任务跟踪。

这是原 Next.js 全栈单体应用的重写版，转向 **Python 主导、前后端分离** 的架构，目标是贴近专业 SaaS 团队的工程实践（分层、鉴权、测试、CI/CD、可观测性、AI Agent）。

---

## 整体架构

前后端分离，单仓库（monorepo）管理两个独立可部署单元：

```
┌─────────────────────────┐        ┌──────────────────────────────┐
│  frontend (Next.js)     │        │  backend (FastAPI)           │
│  浏览器 UI + 登录页       │  HTTP  │  唯一业务入口 + AI Agent      │
│  Vercel/Node 部署        │ ─────▶ │  ─ Router → Service 分层      │
│  仅调用后端 API，不连库    │  JWT   │  ─ LangGraph 智能体           │
└─────────────────────────┘  REST  └──────────────┬───────────────┘
                              /SSE                 │
                                     ┌─────────────┴─────────────┐
                                     ▼                           ▼
                             ┌───────────────┐          ┌────────────────┐
                             │  PostgreSQL   │          │     Redis      │
                             │ 业务/审计数据  │          │  缓存/会话      │
                             │ Agent 图状态   │          │                │
                             └───────────────┘          └────────────────┘
```

关键点：

- **前端只做 UI**：不直连数据库，所有数据都经 FastAPI。这是把「前后端分离」落到实处的架构，也是大厂最常见的分工。
- **后端是唯一业务入口**：REST API + AI Agent（LangGraph 编排的对话式录单/排产），SSE 流式返回。
- **前后端通过标准 JWT 解耦**：前端用 NextAuth 登录并签发 JWT，后端中间件校验，双方不共享 session 存储，可独立部署/扩容。
- **PostgreSQL** 存业务数据、审计日志，以及 LangGraph Agent 的图状态（checkpointer）；**Redis** 用于缓存与会话。

---

## 仓库结构

```
.
├── frontend/            # Next.js 前端（UI 层）——详见 frontend/README.md
├── backend/             # FastAPI 后端（业务 + AI Agent）——详见 backend/README.md
├── docker-compose.yml   # 本地/staging 编排：frontend + backend + postgres + redis
└── .github/workflows/   # CI：backend-ci（lint+test+build）、frontend-ci（lint+typecheck+build）
```

细节文档下沉到各自子目录，避免根文档随实现频繁变动：
- 前端细节 → [frontend/README.md](frontend/README.md)
- 后端细节 → [backend/README.md](backend/README.md)

---

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js (App Router) · React · TypeScript · Tailwind · NextAuth |
| 后端 | FastAPI · SQLAlchemy 2.0 (async) · Alembic · Pydantic |
| AI Agent | LangGraph · DeepSeek（OpenAI 兼容 API，经 langchain-openai） |
| 数据库 | PostgreSQL · Redis |
| 部署 | Docker Compose |
| CI | GitHub Actions |

---

## 本地运行

前置：Docker（守护进程需运行）。

```bash
# 1. 启动全部服务（首次或改了代码用 --build）
docker compose up -d --build

# 2. 建表（首次或有新迁移时）
docker compose exec backend alembic upgrade head

# 3. 创建登录账号
docker compose exec backend python scripts/seed_admin.py owner@filmos.local filmos123

# 4.（可选）灌入演示数据，方便测试看板/排产/Agent
docker compose exec backend python scripts/seed_demo.py
```

打开 http://localhost:3000，用上面的账号登录。

各服务端口：前端 `3000`、后端 `8000`（API 文档 `/docs`）、Postgres `5432`、Redis `6379`。

### 需要自己配置的凭证

以下能力代码已接好，但需要你提供凭证才生效（不提供也不影响其余功能）：

- **AI Agent 对话**：在 `backend/.env` 设 `DEEPSEEK_API_KEY`，然后 `docker compose up -d --force-recreate backend`
- **错误追踪（可选）**：设 `SENTRY_DSN` 启用 Sentry

---

## 状态

前后端核心业务、鉴权、可观测性、CI/CD、AI Agent 均已完成。演示数据脚本仅用于本地测试，不进生产。
