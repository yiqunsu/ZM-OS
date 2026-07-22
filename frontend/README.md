# FilmOS Frontend

Next.js（App Router）前端，是系统的 **UI 层**：渲染界面、处理登录、调用后端 API。**不直连数据库**，所有数据都经 FastAPI 后端。

---

## 职责边界

- **UI 渲染**：订单列表、排产看板（拖拽）、基础数据管理、AI 助手对话。
- **登录鉴权**：用 NextAuth（Credentials）对接后端 `/auth/login`，签发 JWT；中间件保护所有页面，未登录跳转 `/login`。
- **调用后端**：所有请求经 `lib/api.ts` 统一封装，自动带上 JWT；AI 对话用 SSE 流式接收。

后端返回什么，前端就渲染什么——业务规则（状态流转、删除保护等）都在后端，前端不重复实现。

---

## 目录结构

```
app/                    # App Router 页面
├── layout.tsx          #   根布局（Sidebar + SessionProvider）
├── login/              #   登录页
├── kanban/             #   排产看板
├── orders/             #   订单列表 / 新建 / 编辑
├── settings/           #   基础数据（客户/机器/产品/配方）
├── chat/               #   AI 助手（会话侧栏 + 对话）
└── api/auth/           #   NextAuth 路由

components/
├── Sidebar.tsx         #   侧边导航
├── kanban/             #   看板（dnd-kit 拖拽）
├── orders/             #   订单表单
├── settings/           #   各基础数据 Tab
├── chat/               #   ChatInterface（SSE + 确认卡片）
└── ui/                 #   基础组件（button/dialog/input…）

lib/
├── api.ts              #   API 客户端：统一 fetch + JWT + SSE（postStream）
└── utils.ts

auth.ts                 # NextAuth 配置（Credentials → 后端登录 → 签发 JWT）
middleware.ts           # 路由保护（未登录重定向）
```

---

## 与后端的对接

- **字段命名**：后端是 Python 的 snake_case（`order_no`、`spec_params`、`is_active`），前端类型和请求体都按 snake_case 对齐。
- **鉴权**：`auth.ts` 里除了 NextAuth 自身的加密 session，还额外用共享的 `AUTH_SECRET` 签一个后端可校验的 JWT（HS256），`lib/api.ts` 把它放进 `Authorization` 头。
- **API 地址**：由 `NEXT_PUBLIC_API_URL` 指定（默认指向后端 `/api`）。

---

## 开发

```bash
npm install
npm run dev          # 开发服务器（默认 3000）
npm run lint         # ESLint
npm run build        # 生产构建（含 TypeScript 检查）
```

通常直接用根目录的 `docker compose up -d` 一起跑，前端会自动连上后端容器。

### 环境变量（`frontend/.env.local`）

| 变量 | 说明 |
|---|---|
| `AUTH_SECRET` / `NEXTAUTH_SECRET` | 与后端一致的 JWT 密钥 |
| `NEXTAUTH_URL` | NextAuth 回调地址（本地 `http://localhost:3000`） |
| `NEXT_PUBLIC_API_URL` | 后端 API 地址 |
| `NEXT_PUBLIC_SENTRY_DSN` | 可选，前端错误追踪 |
