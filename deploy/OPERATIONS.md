# 部署一致性与识别验收

本地和生产允许域名、数据库地址、凭证不同；不复制生产数据库或密钥来追求一致。
模型、思考模式、输出上限、超时、业务代码、提示词与迁移版本必须可以对照。

## AI 配置

在本地 `backend/.env` 和生产私有 `.env.production` 中分别填写：

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_VISION_MODEL=deepseek-flash
LLM_VISION_THINKING=disabled
LLM_VISION_MAX_TOKENS=8192
LLM_REQUEST_TIMEOUT_SECONDS=60
```

`LLM_MODEL` 也应两端一致。`LLM_VISION_THINKING` 接受 disabled、enabled、provider_default；
仅对官方 api.deepseek.com 发送 thinking 扩展，不再从模型别名猜行为。
其他服务商保留默认行为，报告明确显示 effective=provider_default，不能假定已关闭思考。
修改后必须重新创建 backend 和 agent-worker；单纯 restart 不会更新环境变量。
模型调用的 read timeout 不是整次任务总时限；Worker 仍有独立总时限。

## 本地启动与对照

```bash
./deploy/local-auth/up.sh
python3 deploy/check.py --mode local --output .data/local-report.json
```

生产端只读检查：

```bash
python3 deploy/check.py --mode production --output .data/cloud-report.json
python3 deploy/check.py --mode production --output .data/cloud-report.json --baseline .data/local-report.json
```

先把本地报告安全地复制到服务器作为 baseline。命令仅输出不同字段名，不输出环境全量或密钥。
报告包含运行中 backend/worker 的配置、源码摘要、依赖摘要、迁移和镜像信息；两进程不一致返回非零。
镜像 ID 因平台和 Dockerfile 可以不同，只记录、不直接作相等断言。
带 dirty 的本地版本只是开发诊断，正式发布前应提交、重新构建并重新验收。
`unknown` 版本不能证明一致。报告匹配不能保证基础数据或随机模型输出完全一致。

## 真实图片验收

本地执行（调用真实付费模型，只发送仓库合成图片，不创建订单）：

```bash
docker compose exec -T agent-worker python scripts/verify_vision.py
```

线上执行：

```bash
docker compose --env-file deploy/production/.env.production -f deploy/production/compose.yml exec -T agent-worker python scripts/verify_vision.py
```

合成图片为 `backend/scripts/fixtures/order.png`；使用实际提取提示词、动态 schema 和 HTTP 适配器，
核验一笔订单、705 mm、80 μm、1200 kg。允许等价单位转换，不比较模型文字。
失败返回非零且只输出安全错误码。这是模型链路验收，不替代浏览器/Worker 全链路。
仍须在网页登录、上传该图、明确点击识别，检查草稿与刷新后的结果；不必确认创建正式订单。
复杂业务图片和客户/产品匹配需另行人工核对。

## 发布与记录

生产 `scripts/deploy.sh` 拒绝有未提交或未跟踪源码的工作区，不自动清理用户改动。
backend/worker 使用同一个 Git SHA 标签镜像，frontend 也用 SHA 标签；发布保存镜像 ID、运行参数与迁移证据到
`.data/releases/时间戳-SHA/`。镜像中烘焙 revision，`/health` 可查看 backend 版本。
开发与生产固定相同 Node/Python 基础版本，前端使用 npm ci、后端用 requirements.lock 约束包含传递依赖的安装版本。更新依赖时必须同步约束并重新构建验收。
这仍是服务器构建流程，不是跨机器使用同一镜像 digest 的制品晋级流程；镜像仓库和 CI 发布需后续配置。
Git SHA 标签禁止覆盖重推；严格跨环境制品一致需改为可信镜像仓库 digest 部署。

部署脚本自动执行运行对照和一次真实付费合成图片验收，失败返回非零，结果保存在 release 目录。
失败时不自动回滚数据库或停止已运行服务。仍需验证浏览器上传与 OIDC 登录、刷新、OWNER/OPERATOR 权限。
容器 healthy 只表示进程健康，不等于 AI 功能验收通过。
回滚应用镜像前评估迁移兼容性；不可自动回滚数据库。

## 本次腾讯云上线待办

- 合并并提交经过本地验证的改动，再部署；目前尚未修改云端。
- 对齐上述模型参数，复测曾经 OUTPUT_TRUNCATED 的截图。
- 补齐 FilmOS 登录 Logo、CSS：按 production/README.md 的既有 Casdoor 应用更新步骤执行。
  已初始化数据库不会被初始化脚本覆盖；不能删除初始化标记或清库来更新外观。
