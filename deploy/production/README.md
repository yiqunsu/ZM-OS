# FilmOS production deployment

部署目录和环境选择见[部署总入口](../README.md)。

> 正式发布先按 [版本发布规则](../../meta/RELEASING.md)检出目标版本标签，再运行 `./deploy/production/scripts/deploy.sh`。第 6 节的分支拉取方式仅用于旧流程。

本目录用于把 FilmOS 部署到腾讯云轻量应用服务器。生产栈由 Caddy、Next.js、FastAPI、AI Worker、Casdoor 和 PostgreSQL 组成；后端与 Worker 共用镜像。本地与生产统一使用 `backend/Dockerfile` 和 `frontend/Dockerfile`；本 Compose 选择后端 `production` target，并显式传入前端 Casdoor 模式及 API 地址。Redis、Phoenix、Sentry、Loki、COS 不在第一版生产范围内。

ICP备案通过前，Caddy 只监听服务器 `127.0.0.1`，必须通过 SSH 隧道访问。备案通过前不要添加公网 DNS，也不要开放公网 80/443。

## 1. 服务与数据边界

- Caddy 是唯一发布宿主机端口的容器，分别代理 FilmOS 与 Casdoor 两个域名；
- FastAPI、Next.js、Casdoor 与 PostgreSQL 没有宿主机端口；
- FilmOS 与 Casdoor 共用 PostgreSQL 进程，但使用不同数据库和不同登录账号；
- FilmOS 业务数据存于 `filmos_postgres_data`；Casdoor 账号、角色和应用配置也在该 PostgreSQL 卷的独立数据库中；
- 聊天图片正文存于后端私有的 `filmos_chat_attachments` 卷，附件元数据仍在 FilmOS 数据库；

## 2. 服务器准备

服务器应为 Ubuntu 24.04 x86_64，并已安装 Docker 与 Compose：

```bash
docker --version
docker compose version
free -h
df -h
sudo install -d -o ubuntu -g ubuntu -m 0750 /opt/filmos
```

使用只读 GitHub deploy key 克隆仓库到 `/opt/filmos`。不要通过聊天、Git 或命令截图传输私钥、环境文件、密码或 API Key。

## 3. 需要你确定和填写的值

复制模板并限制权限：

```bash
cd /opt/filmos
install -m 0600 deploy/production/.env.production.example deploy/production/.env.production
nano deploy/production/.env.production
```

必须自行生成并保存以下秘密：

```bash
openssl rand -hex 24   # 两个数据库密码
openssl rand -hex 32   # AUTH_SECRET、OIDC client secret
openssl rand -hex 16   # OIDC client ID
openssl rand -base64 32 # 两个 Casdoor 初始账号密码
```

需要做出的业务选择只有这几项：

- `CASDOOR_ADMIN_EMAIL`：平台管理员邮箱；只用于 Casdoor 管理后台；
- `CASDOOR_OWNER_NAME`：首个 FilmOS 管理员的 Casdoor 用户名；
- `CASDOOR_OWNER_EMAIL`：必须与现有 FilmOS OWNER 的邮箱完全一致（忽略大小写），这样首次 OIDC 登录会保留原本的本地用户 ID、订单和 Agent 会话；
- `CASDOOR_ADMIN_PASSWORD` 与 `CASDOOR_OWNER_PASSWORD`：两个不同的强密码；
- `LLM_API_KEY`：后端 Agent 使用的模型 API Key。

`NEXT_PUBLIC_API_URL` 是写入前端浏览器 bundle 的构建期 API base，默认同源 `/api`。只有在 API 使用其他公开 origin 时才需要覆盖；修改后必须重新运行部署脚本以重建前端镜像，不能只重启容器。

使用 DeepSeek 官方 API 时，在服务器私有配置中设置：

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
LLM_VISION_MODEL=deepseek-flash
LLM_VISION_THINKING=disabled
LLM_VISION_MAX_TOKENS=8192
LLM_REQUEST_TIMEOUT_SECONDS=60
```

另外填写自己的 `LLM_API_KEY`。模型参数应与本地验证时一致；修改后重新运行部署脚本，使后端和 Worker 同时更新。thinking 对官方 DeepSeek 显式设置，不再按模型别名猜测；其他供应商不发送该扩展。

可选的电脑微信扫码登录还需要微信开放平台审核通过的“网站应用”凭证：

- `WECHAT_LOGIN_ENABLED`：默认 `false`；只有备案、正式域名和 HTTPS 均生效后才能设为 `true`；
- `WECHAT_OPEN_APP_ID`：网站应用 AppID；
- `WECHAT_OPEN_APP_SECRET`：网站应用 AppSecret，只保存在服务器环境文件和 Casdoor 数据库中。

不要把 Casdoor 平台管理员和日常 FilmOS OWNER 当成同一个账号。环境校验会拒绝占位符、弱默认管理员密码、重复数据库角色、错误域名和不精确的 callback URL。

## 4. 备案期间的私有部署

保留模板中的私有地址：

```dotenv
WEB_BIND_IP=127.0.0.1
APP_SITE_ADDRESS=http://app.filmos.test
AUTH_SITE_ADDRESS=http://auth.filmos.test
APP_PUBLIC_URL=http://app.filmos.test:8080
NEXTAUTH_URL=http://app.filmos.test:8080
CASDOOR_ISSUER=http://auth.filmos.test:8080
CASDOOR_REDIRECT_URI=http://app.filmos.test:8080/api/auth/callback/casdoor
```

校验并部署：

```bash
./deploy/production/scripts/validate-env.sh
./deploy/production/scripts/deploy.sh
```

首次部署会：

1. 顺序构建后端和前端，降低 2c/4GB 主机峰值内存；
2. 创建独立的 Casdoor 数据库账号和数据库；
3. 在 `.data/casdoor/` 生成权限为 `0600` 的运行配置和初始化数据；
4. 用强密码替换 Casdoor 的 `built-in/admin` 默认账号，创建 `filmos` 组织、OIDC 应用、签名证书、`filmos-owner` 与 `filmos-operator`；
5. 将初始化切换为 create-only，后续重启不会覆盖新增用户和角色成员；
6. 备份已有数据库、执行 Alembic migration，再启动应用入口。

在本地 Mac 的 `/etc/hosts` 增加：

```text
127.0.0.1 app.filmos.test auth.filmos.test
```

然后保持 SSH 隧道运行：

```bash
ssh -L 8080:127.0.0.1:80 ubuntu@42.192.114.38
```

访问 [http://app.filmos.test:8080](http://app.filmos.test:8080)。OIDC 会跳转到 `auth.filmos.test:8080`，两个地址必须都从同一隧道访问。

首次验证时确认：

- 用 `CASDOOR_OWNER_NAME` / `CASDOOR_OWNER_PASSWORD` 登录 FilmOS；
- `/api/auth/me` 返回原有 FilmOS OWNER 的同一个本地 ID；
- 原有订单与 Agent 会话仍可见；
- 退出后再次打开 FilmOS 不会静默恢复上一个人的 Casdoor 会话。

## 5. Casdoor 用户与角色管理

通过 `http://auth.filmos.test:8080`（公网启用后为 `https://auth.zmorder.cn`）登录 Casdoor 管理后台。平台管理使用 `built-in/admin` 与 `CASDOOR_ADMIN_PASSWORD`。

新增业务用户时：

1. 用户必须属于 `filmos` 组织并填写唯一有效邮箱；
2. 只分配 `filmos-owner` 或 `filmos-operator` 其中一个角色；
3. 不要开启 FilmOS 应用的自助注册；
4. 不要启用动态客户端注册；
5. 角色变化最多在当前 15 分钟 access token 到期后生效。

`filmos-owner` 可修改基础数据；`filmos-operator` 可读取基础数据并管理订单、生产任务及自己的 Agent 会话。账号和角色不在 FilmOS 页面内维护。

### 5.1 登录页外观

登录页面由 Casdoor 的 `app-filmos` 提供。`branding/login.css` 定义浅灰背景、白色登录卡片和手机布局；`branding/filmos-logo.svg` 由认证域名下的 Caddy 同源提供，避免空 Logo 或外部图床失效导致破图。认证、密码恢复和微信入口继续使用 Casdoor 原生表单。

新数据库初始化自动使用这些外观配置。**已有数据库不会覆盖应用配置**，更新仓库并部署 Caddy 后，在 Casdoor 管理后台编辑 `app-filmos`：

1. Logo 填写 `https://auth.zmorder.cn/branding/filmos-logo.svg`（私有模式使用对应认证域名）；
2. Form CSS 和 Form CSS Mobile 均粘贴 `deploy/production/branding/login.css` 全文，不包裹 `<style>`；
3. Form position 选择 Center，保存后从 FilmOS 重新发起登录；
4. 验证 Logo URL 返回 SVG；在桌面和手机检查输入框、错误提示、密码恢复、语言切换及启用后的微信标签。

更新前先保存原有 Logo/CSS/位置字段，回滚时恢复这些字段。不要删除 `.initialized`、清空 Casdoor 数据库或用整个初始化 JSON 覆盖现有用户来应用外观。

### 5.2 电脑微信扫码登录（可选）

微信扫码只支持微信开放平台的“网站应用”，授权回调域填写 `auth.zmorder.cn`。备案、DNS、HTTPS 和微信应用审核全部生效前保持：

```dotenv
WECHAT_LOGIN_ENABLED=false
WECHAT_OPEN_APP_ID=
WECHAT_OPEN_APP_SECRET=
```

全新 Casdoor 数据库可在公网首次部署前填写 AppID/AppSecret 并将开关改为 `true`，初始化程序会创建 `OAuth / WeChat / Web` Provider。配置固定为允许登录和解绑、禁止注册，并使用空 binding rule 禁止按昵称、邮箱或手机号自动合并账号。密码入口会保留。

已有 Casdoor 数据库不会由部署脚本直接改写内部表。先以 `built-in/admin` 登录 Casdoor 控制台并完成以下操作：

若页面没有微信入口，先检查 `app-filmos` 的 Providers 和 Signin methods。`WECHAT_LOGIN_ENABLED=true` 只是初始化/部署验证开关，**对已有数据库仅改环境变量、重启容器不会新增入口**。AppID/AppSecret 仅在服务器私有环境文件和 Casdoor 后台填写，不发到聊天或提交到 Git。

1. 在 Providers 新增 `OAuth / WeChat / Web`，名称为 `provider-wechat-web`，填写网站应用 AppID/AppSecret；
2. 编辑 `app-filmos`，绑定该 Provider，开启 Can signin/Can unlink，关闭 Can signup，并清空 Binding rule；
3. 在 Signin methods 保留 Password，并新增 `WeChat`、规则选择 `Tab`；
4. 再把环境开关设为 `true` 并运行部署。验证脚本会在配置不完整时停止发布。

员工采用邀请制：

1. 管理员在 `filmos` 组织创建用户，填写与 FilmOS 相同的唯一邮箱和临时强密码；
2. 只把用户加入 `filmos-owner` 或 `filmos-operator` 其中一个角色；
3. 员工首次使用临时密码登录 Casdoor，在账号设置的第三方账号区域绑定微信；
4. 退出后重新从 FilmOS 发起登录，使用微信二维码验证；
5. 未绑定的陌生微信必须得到“不允许注册/请联系管理员”的拒绝，不得创建业务账号。

若微信服务不可用，员工仍可使用 Casdoor 密码登录。紧急关闭入口时将 `WECHAT_LOGIN_ENABLED=false`，并在 Casdoor `app-filmos` 中移除微信登录方式；不要删除用户、角色或已经保存的微信标识。

## 6. 日常更新、健康和日志

在服务器的 `/opt/filmos` 中执行。先确认处于 `main`，检查未提交改动；环境文件保留在服务器上，不要再次复制模板覆盖。

```bash
cd /opt/filmos
git status --short
git pull --ff-only
./deploy/production/scripts/deploy.sh
```

脚本只负责配置校验、顺序构建、登录服务准备、停止应用写入、已有数据备份、数据库迁移、启动和健康/数据库结构检查。不会自动调用付费模型，也不生成发布报告或要求本地/云端报告对照。成功后在网页上检查登录和一次 AI 操作；容器健康不等于模型功能已验证。

前后端固定使用 `production` 镜像标签，后端和 Worker 共用一个镜像。每次都让 Docker 检查构建缓存，因此同一提交修改前端域名参数也会重新构建对应步骤。Git revision 仅作镜像内版本记录；未提交改动会显示警告并标记 `-dirty`，不会自动清理或阻止发布。推荐从已提交的 `main` 发布。

后端保留 `requirements.lock` 固定依赖版本，使用 BuildKit 下载缓存；变更代码或版本号不会使依赖安装层失效，安装失败后再次构建也可复用已缓存下载。首次仍需从软件源下载，缓存不能保证云端网络一定可用。不要用 `--no-cache` 或清理构建缓存来处理下载慢。

生产 Compose 默认从腾讯云 HTTPS PyPI 镜像下载 Python 依赖，以避开服务器连接 `files.pythonhosted.org` 超时的问题。现有环境文件无需新增配置。需要切换源时，可在 `.env.production` 设置 `PIP_INDEX_URL=https://pypi.org/simple`（或其他受信 HTTPS 镜像），再运行部署脚本；这个值传给 Docker 构建，宿主机的 pip 配置不会自动传入。依赖版本仍由原锁文件约束；镜像源缺包时应检查同步状态或切换源，不删除版本约束、不关闭 TLS 校验。

构建失败不会停止现有应用；登录服务验证完成后，先停止 frontend、backend、agent-worker，再备份和迁移。备份失败不会执行迁移，备份或迁移失败都会保持应用停止；应排查后重新发布，不会自动恢复旧进程。失败时保留日志，不删除数据库卷、不自动恢复备份。固定标签不提供按 Git 标签直接回滚镜像的能力；需要回退时检出兼容的旧提交并重新构建，数据库另行评估。

查看状态与日志：

```bash
docker compose --env-file deploy/production/.env.production -f deploy/production/compose.yml ps
docker compose --env-file deploy/production/.env.production -f deploy/production/compose.yml logs --tail=100 casdoor
docker compose --env-file deploy/production/.env.production -f deploy/production/compose.yml logs --tail=100 backend
docker compose --env-file deploy/production/.env.production -f deploy/production/compose.yml logs --tail=100 frontend
```

所有容器使用 `10MB × 3` 的 Docker JSON 日志轮转。不要用 `git reset --hard` 处理服务器上的异常改动。

## 7. 成组备份

```bash
./deploy/production/scripts/backup.sh manual
```

每次成功会生成同一时间戳的四个文件：

- `filmos_...dump`：FilmOS 业务数据库；
- `casdoor_...dump`：Casdoor 登录与角色数据库；
- `chat_attachments_...tar.gz`：聊天图片附件卷；
- `backup_...sha256`：两份 dump 和附件归档的校验清单。

只有两份 dump 能被 `pg_restore --list` 读取且附件归档能被 `tar` 校验后，备份才算成功。数据库与附件必须使用同一时间戳的一组文件恢复；可用 cron 每天执行并清理超过七天的旧备份。在没有 COS 的阶段，应定期把一整组文件下载到另一台设备。本机备份无法抵御整台服务器或云账号丢失。

## 8. 恢复

恢复会替换目标数据库并丢弃备份时间点之后的写入，必须明确确认。先在可读时再做一份最新备份。

恢复 FilmOS：

```bash
./deploy/production/scripts/restore.sh \
  /opt/filmos/.data/backups/filmos_TIMESTAMP_manual.dump \
  --confirm-database-replacement
```

恢复 Casdoor：

```bash
./deploy/production/scripts/restore-casdoor.sh \
  /opt/filmos/.data/backups/casdoor_TIMESTAMP_manual.dump \
  --confirm-database-replacement
```

恢复同一时间戳的聊天附件：

```bash
./deploy/production/scripts/restore-attachments.sh \
  /opt/filmos/.data/backups/chat_attachments_TIMESTAMP_manual.tar.gz \
  --confirm-attachment-replacement
```

恢复失败会保持应用写入服务停止，避免在半恢复状态继续产生数据。应优先使用同一 manifest 中的数据库和附件备份；只恢复其中一项前必须理解身份配置、业务用户映射或附件元数据可能出现的时间差。

## 9. ICP 通过后启用公网

先为 `app.zmorder.cn` 和 `auth.zmorder.cn` 都添加指向 `42.192.114.38` 的 A 记录，并开放 TCP 80/443。然后只修改以下环境值：

```dotenv
WEB_BIND_IP=0.0.0.0
APP_SITE_ADDRESS=app.zmorder.cn
AUTH_SITE_ADDRESS=auth.zmorder.cn
APP_PUBLIC_URL=https://app.zmorder.cn
NEXTAUTH_URL=https://app.zmorder.cn
CASDOOR_ISSUER=https://auth.zmorder.cn
CASDOOR_REDIRECT_URI=https://app.zmorder.cn/api/auth/callback/casdoor
```

重新运行校验和部署。初始化时已经白名单化私有与正式域名的精确 callback/logout URL，不使用通配符；Casdoor issuer 会由运行配置切换到正式 HTTPS 地址。

上线前还必须：

- 在页面展示真实 ICP 备案号及规定链接；
- 验证两个域名的 HTTPS、OIDC discovery、JWKS、登录、刷新、退出、OWNER/OPERATOR 权限和 Agent SSE；
- 按要求完成公安联网备案；
- 若失败，暂停 DNS/关闭公网 80/443，恢复私有环境值后重新部署。

## 10. 不可跨越的边界

- 不公开 PostgreSQL 5432、FastAPI 8000、Next.js 3000、Casdoor 8000；
- 不把 `.env.production`、`.data/`、Token、密码或证书私钥提交到 Git；
- 不为了“未来可能需要”提前加入 Redis；
- 不在未明确访问控制、保留策略、隐私与成本前把 Phoenix、Sentry 或 Loki 加入生产；
- 不自动恢复迁移前备份。数据库恢复是破坏性操作，必须人工选择。

## 本地与生产的一致性边界

本地统一入口为 `./deploy/local/up.sh`；加 `--casdoor` 使用与生产相同的 OIDC/RBAC 登录方式，加 `--phoenix` 开启可选追踪。本地 Casdoor 初始化工具位于 `deploy/local/casdoor/`，配置与说明统一归入本地 env 和部署总 README。

| 项目 | 本地 Casdoor 模式 | 生产 |
| --- | --- | --- |
| 业务源码、数据库迁移、Worker | 同一工作区代码和 Alembic 链路，API/Worker 共用镜像 | 相同；要对比效果须部署相同提交 |
| 登录 | Casdoor，localhost 地址 | 同一 Casdoor 镜像，正式或隧道域名 |
| 请求入口 | 前端 3000、API 8000、登录 8001 | Caddy 统一入口；公开模式使用 HTTPS |
| 发布步骤 | 构建、准备依赖、停写、迁移、启动、健康/结构检查 | 同样步骤，另有配置/登录验证与迁移前备份 |
| 模型 | `deploy/local/.env` | `.env.production`；默认参数相同，实际值需保持一致 |
| 后端运行用户 | local target，保留本地卷访问方式 | production target，非 root 用户，启用代理头处理 |
| 数据库镜像 | `postgres:16` | `postgres:16.10-alpine`；同主版本但非相同镜像 |
| 运维 | 方便本机访问；备份按需手动执行 | 内部网络、重启策略、日志轮转、资源限制和持久备份 |

自动化配置对照覆盖共享源码、登录模式、Worker 命令、API/Worker 配置及卷一致性、默认模型参数。它不能替代完整 OIDC、反向代理/SSE、真实模型和业务数据验收。数据库镜像对齐前应确认已有卷的版本并备份，不直接降级已有数据库。

## 默认配置（2026-09-27）

- 默认启用前端、API、Worker、PostgreSQL、Casdoor、Caddy；`AGENT_V2_ENABLED=true`。Redis、OpenClaw、Phoenix 不部署，Sentry 关闭。
- 默认使用 Casdoor 密码登录，微信登录关闭；平台管理员为 `admin`，日常业务管理员为 `owner`。两个账号使用不同密码，邮箱需填写实际地址；迁移旧账号时业务管理员邮箱应与原账号一致。
- 数据库账号分别为 `filmos`、`casdoor`，数据库密码、登录密码、Auth.js 密钥及 OIDC 客户端密钥各自随机生成，不使用通用默认密码。
- 模型默认沿用本地配置：地址 `https://api.deepseek.com`，文本 `deepseek-v4-flash`，视觉 `deepseek-flash`；视觉 thinking 关闭，输出上限 8192，超时 60 秒。这里只同步配置，未调用模型验证可用性；API Key 需自行填写。
- 访问方式暂保留私有隧道模式；不会自动打开公网监听。公网模式配置见前文。

当前工作区已准备被 Git 忽略的 `.env.production`（权限 0600），独立随机密码已写入但不在文档展示。使用前填写两个真实邮箱和 `LLM_API_KEY`；不要再次复制模板覆盖它。生产配置文件包含秘密，仅通过私密渠道传到目标服务器。
