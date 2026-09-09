# FilmOS Frontend

development 新增 `components/chat/SchedulingWorkspace.tsx`：聊天右侧生产监控与草案编辑。
实际队列每五秒刷新；草案订单可拖到机器、新任务、已有草案任务或未安排区，
也可使用下拉框移动、箭头重排。每次修改由后端校验保存，再显示权威结果。
执行前二次核对，绑定草案内容版本；后台数据变化后禁止执行并要求重新生成。

Next.js（App Router）前端，是系统的 **UI 层**：渲染界面、处理登录、调用后端 API。**不直连数据库**，所有数据都经 FastAPI 后端。

---

## 职责边界

- **UI 渲染**：订单列表、排产看板（拖拽）、基础数据管理、AI 助手对话。
- **登录鉴权**：生产环境用 Auth.js 对接 Casdoor OIDC，并在服务端刷新短期 access token；`proxy.ts` 保护页面，未登录跳转 `/login`。Credentials 只保留给本地开发。
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

auth.ts                 # Auth.js 配置（Casdoor OIDC + 服务端 Token 刷新）
proxy.ts                # 路由保护 + OWNER 专属设置页保护
```

---

## 与后端的对接

- **字段命名**：后端是 Python 的 snake_case（`order_no`、`spec_params`、`is_active`），前端类型和请求体都按 snake_case 对齐。
- **鉴权**：生产环境的 Auth.js 加密 Cookie 保存 Casdoor access/refresh token；浏览器 Session 只得到短期 access token、本地用户 ID、邮箱与角色。`lib/api.ts` 把短期 Token 放进 `Authorization` 头，FastAPI 通过 JWKS 验证并执行 RBAC。
- **刷新与退出**：refresh token 和 OIDC client secret 不返回浏览器。刷新失败会清理登录状态；正常退出同时清理 Auth.js 与 Casdoor SSO 会话。
- **权限展示**：OPERATOR 看不到基础数据入口且不能直接访问 `/settings`，但真正的写权限仍由 FastAPI 决定。
- **API 地址**：由构建期变量 `NEXT_PUBLIC_API_URL` 指定。本地 Docker 镜像默认使用 `http://localhost:8000/api`，生产镜像默认使用同源 `/api`。

---

## 开发

```bash
npm install
npm run dev          # 开发服务器（默认 3000）
npm run lint         # ESLint
npm run build        # 生产构建（含 TypeScript 检查）
```

通常直接用根目录的 `docker compose up -d` 一起跑，前端会自动连上后端容器。

`NEXT_PUBLIC_*` 会在 Next.js 构建时写入浏览器 bundle。根 Compose 会把 `NEXT_PUBLIC_API_URL` 作为 build arg 传入；如需覆盖，在运行 Compose 前通过 shell 或仓库根目录 `.env` 设置，然后重新执行 `docker compose build frontend`。只修改容器的 runtime `env_file` 不会改变已经构建的前端地址。

### 环境变量（`frontend/.env.local`）

| 变量 | 说明 |
|---|---|
| `AUTH_PROVIDER` | 服务端 `local` 或 `casdoor`；生产固定 `casdoor` |
| `NEXT_PUBLIC_AUTH_PROVIDER` | 构建登录页模式；生产固定 `casdoor` |
| `AUTH_SECRET` / `NEXTAUTH_SECRET` | Auth.js Cookie 密钥；仅本地模式同时用于开发 JWT |
| `NEXTAUTH_URL` | Auth.js 回调地址 |
| `CASDOOR_ISSUER` / `CASDOOR_PUBLIC_URL` | 外部 Casdoor OIDC origin |
| `CASDOOR_INTERNAL_URL` | Next.js 容器访问 Casdoor 的私网地址 |
| `CASDOOR_CLIENT_ID` / `CASDOOR_CLIENT_SECRET` | OIDC 客户端凭证；secret 仅服务端可见 |
| `NEXT_PUBLIC_CASDOOR_URL` | 浏览器联合退出所用 Casdoor 地址 |
| `NEXT_PUBLIC_CASDOOR_CLIENT_ID` | 联合退出使用的公开 client ID |
| `NEXT_PUBLIC_API_URL` | 构建期后端 API base，必须包含后端路由前缀 `/api` |
| `NEXT_PUBLIC_SENTRY_DSN` | 可选，前端错误追踪 |
