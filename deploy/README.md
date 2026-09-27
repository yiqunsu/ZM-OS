# FilmOS 部署入口

`deploy/` 集中管理部署脚本、环境配置示例和操作说明。下列命令均从仓库根目录执行。`main` / `development` 是代码分支；部署脚本使用当前检出的工作区代码，不自动切换分支或拉取 GitHub。

## 目录与职责

```text
deploy/
├── README.md           # 部署总入口（本文件）
├── local/
│   ├── up.sh           # 唯一本地启动入口
│   ├── docker-compose.yml # 本地基础服务
│   ├── compose.local-auth.yml # 可选 Casdoor
│   ├── compose.phoenix.yml # 可选 Phoenix
│   ├── .env.example    # 本地配置模板（实际 .env 不提交）
│   └── casdoor/        # 可选 Casdoor 数据库初始化工具
└── production/
    ├── README.md       # 生产准备、发布、备份与恢复说明
    ├── compose.yml     # 生产服务与网络配置
    ├── Caddyfile       # 生产反向代理
    ├── scripts/        # 发布、校验、备份、恢复等操作脚本
    ├── branding/       # 登录页品牌资源
    └── tests/          # 本地/生产部署回归及备份恢复演练
```

镜像定义与应用代码放在一起：[后端 Dockerfile](../backend/Dockerfile)、[前端 Dockerfile](../frontend/Dockerfile)。本地与生产共用它们，通过 target 和构建参数区分环境。

本地服务定义集中在 `deploy/local/`：[默认 Compose](local/docker-compose.yml)、[Casdoor 扩展](local/compose.local-auth.yml)、[Phoenix 扩展](local/compose.phoenix.yml)。这些配置共同组成同一个本地部署入口。

## 选择启动方式

| 场景 | 命令 | 常驻服务（AI 开启时） |
| --- | --- | --- |
| 本地账号登录 | `./deploy/local/up.sh` | 前端、API、Worker、PostgreSQL，共 4 个 |
| 本地验证生产登录流程 | `./deploy/local/up.sh --casdoor` | 上述服务加 Casdoor，共 5 个 |
| 本地开启 AI 追踪 | 在本地命令末尾加 `--phoenix` | 再增加 Phoenix |
| 生产发布 | `./deploy/production/scripts/deploy.sh` | 前端、API、Worker、PostgreSQL、Casdoor、Caddy，共 6 个 |

Casdoor 模式另有一次性初始化步骤，迁移也使用临时容器，不计入常驻服务。Redis 和 OpenClaw 均不需要。

## 配置文件放在哪里

已有配置时先检查并保留，不直接覆盖。秘密只填写到本地实际配置文件，不提交到 Git。

| 场景 | 实际配置文件 | 模板与填写说明 |
| --- | --- | --- |
| 本地全部服务 | `deploy/local/.env` | [模板](local/.env.example)：本地密钥、模型、前端地址及可选 Casdoor 配置；[登录说明](#本地-casdoor-登录) |
| 生产 | `deploy/production/.env.production` | [模板](production/.env.production.example)及[生产说明](production/README.md)：域名、登录、数据库、模型与备份配置 |

默认本地部署无需根目录 `.env` 或前后端各自的 env，数据库连接和附件目录由 Compose 提供。本地所有模式只维护这一份 env，Compose 按服务分配配置，前端不会收到模型 Key 或数据库密码。生产使用独立 env，不读取本地配置。

本地首次准备和账号创建命令见[根 README](../README.md#本地运行)。本地启动脚本不会自动创建普通登录账号或导入演示数据；Casdoor 初始账号由其配置初始化。

生产服务、账号和模型的默认选择见[默认配置](production/README.md#默认配置2026-09-27)。

## 启动和升级会做什么

本地流程：校验配置 → 构建镜像 → 启动数据库及可选登录服务 → 停止已有应用写入 → Alembic 迁移 → 启动应用 → 健康与数据库结构检查。

生产流程在此基础上增加严格配置和登录校验，并在停止应用写入后、迁移前备份已有数据库与附件。构建失败不停止现有应用；备份或迁移失败保持应用停止，等待排查。脚本不删除数据卷，不自动恢复备份，也不调用付费模型。

删除容器不等于删除数据卷；再次启动可能继续使用原有数据库和附件。正式部署前应确认目标环境和已有数据。

## 本地与生产能否表现一致

业务代码、Worker、Alembic 迁移和镜像定义共用。比较效果时需要相同代码版本、模型配置和相应测试数据；本地选择 `--casdoor` 才覆盖生产使用的登录流程。

生产额外使用 Caddy、域名/HTTPS、内部网络、非 root 后端、资源限制、日志轮转和自动备份。本地 PostgreSQL 为 `postgres:16`，生产为 `postgres:16.10-alpine`，尚未统一镜像标签。完整差异和验收边界见[生产说明](production/README.md#本地与生产的一致性边界)。

自动化部署检查见[测试规范](../meta/TESTING.md)。容器健康和配置检查不能替代真实登录、模型调用和业务操作验收。

手动执行本地 Compose 命令时也必须指定配置，例如 `docker compose --env-file deploy/local/.env -f deploy/local/docker-compose.yml ps`。启动脚本会自动选择该文件；可用 `FILMOS_LOCAL_ENV_FILE` 指定另一份本地配置。

## 本地 Casdoor 登录

默认本地使用应用自带账号；需要验证生产使用的 OIDC/RBAC 登录流程时，在 `deploy/local/.env` 填好 Casdoor 配置段，执行：

```bash
./deploy/local/up.sh --casdoor
```

网站地址默认 `http://localhost:3000`，Casdoor 默认 `http://localhost:8001`，其端口仅绑定本机回环地址。`CASDOOR_AUTH_SECRET` 与普通本地登录的 `AUTH_SECRET` 分别保留；新数据库可直接使用配置中的 Casdoor 业务管理员账号。如果要验证旧账号关联，`CASDOOR_OWNER_EMAIL` 应与已有 FilmOS OWNER 邮箱一致。

扩展配置创建独立数据库和账号，共有五个常驻服务、两个一次性 Casdoor 初始化服务。数据库初始化脚本位于 `local/casdoor/init-database.sh`，无需手动调用。Casdoor 使用独立的应用网络和内部数据库网络；品牌资源同时提供给配置生成工具与登录页面。API 和 Worker 仍共用业务数据库和附件卷。

前端浏览器 API 默认 `http://localhost:8000/api`；修改 `NEXT_PUBLIC_API_URL` 后需重新执行启动脚本构建镜像。可以追加 `--phoenix` 开启追踪。

恢复普通本地登录时，先停止带 Casdoor 的服务组合，再启动默认模式：

```bash
docker compose --env-file deploy/local/.env \
  -f deploy/local/docker-compose.yml -f deploy/local/compose.local-auth.yml down
./deploy/local/up.sh
```

不加 `-v`，保留数据库卷。生成的 Casdoor 配置位于 `.data/local-casdoor/`，被 Git 忽略；不要为了切换登录模式删除该目录或数据库卷。

本地 Compose 项目名固定为 `zm-os`，保留原有 `zm-os_pgdata` 和 `zm-os_chat_attachments` 卷；文件移动不创建另一套本地数据。显式设置 `COMPOSE_PROJECT_NAME` 或 `-p` 仍可覆盖项目名，用于独立环境。
