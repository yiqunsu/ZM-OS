# FilmOS 测试与验证规范

状态：Normative

测试应证明业务不变量，而不只是覆盖代码行。交付前运行与改动风险相称的检查；无法运行时必须说明原因和未验证范围。

## 1. 当前基线

- 后端：Pytest + pytest-asyncio，测试数据库为 PostgreSQL `filmos_test`；
- 后端静态检查：Ruff；
- 前端静态检查：ESLint + TypeScript；
- 前端生产验证：Next.js build；
- CI 配置位于 `.github/workflows/`；
- 当前尚无正式前端单元测试或端到端测试框架，不得虚构测试命令。

## 2. 常用命令

### 后端本地环境

在 `backend/` 目录运行：

```bash
venv/bin/ruff check .
venv/bin/python -m pytest -q
```

### 后端容器与迁移

在仓库根目录运行：

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
docker compose exec backend alembic check
```

### 前端

在 `frontend/` 目录运行：

```bash
npm run lint
npm run build
```

### 容器配置与运行状态

在仓库根目录运行：

```bash
docker compose config --quiet
docker compose ps
curl -fsS http://localhost:8000/health
```

## 3. 按改动类型的最低要求

| 改动 | 最低验证 |
| --- | --- |
| 后端 Service / Router / Schema | Ruff、相关 Pytest；业务规则变化时运行完整后端测试 |
| SQLAlchemy Model / Alembic | Ruff、完整后端测试、空库升级到 head、`alembic check` |
| 前端页面 / 组件 / API 调用 | ESLint、TypeScript/Next build、关键交互手动验证 |
| 鉴权与权限 | 登录成功/失败、未认证、不同角色、Token 失效测试 |
| 看板与排产 | 后端事务测试、失败回滚、并发/重复操作测试、前端交互验证 |
| Phoenix / OpenTelemetry | 启用与禁用启动路径、Trace 可见性、采集端不可用时业务 API 仍正常 |
| Docker / 环境配置 | `docker compose config --quiet`、重建受影响镜像、健康检查 |
| 仅文档 | 检查链接、命令和文件路径；确认未与 Ground Truth/ADR 冲突 |

## 4. 后端测试规则

- 每条新增业务不变量至少有一个成功测试和一个拒绝非法输入的测试。
- 多实体写操作必须测试事务回滚，确保失败后没有部分数据残留。
- 涉及编号、队列位置、订单占用时，应测试并发或唯一冲突处理。
- 删除保护必须同时测试“有关联时拒绝”和“无关联时成功”。
- 状态迁移必须测试合法路径和非法跳转。
- API 测试不能只断言状态码；应验证持久化后的关联、状态和快照。
- 测试不得依赖执行顺序，不得连接或清空正式业务数据库。
- 测试建表不能永久替代 Alembic 链路验证；CI 应单独验证 migration。

## 5. 前端验证规则

- 所有写操作至少验证成功、后端拒绝和网络失败三种结果。
- 乐观更新必须验证失败后状态恢复。
- 表单验证应覆盖必填项、数值边界和后端错误展示。
- 看板应验证创建任务、跨任务移动、跨机器移动、拆分、合并、排序、完成和删除。
- 关键路径应逐步引入端到端测试；优先覆盖订单录入和看板排产。
- ESLint warning 应被视为待处理问题，不得长期通过降级规则无限累积。

## 6. 数据库迁移验证

数据库改动至少验证：

1. 从空数据库执行全部 migration 能到达 `head`；
2. 已有结构升级成功，必要的数据迁移结果正确；
3. ORM metadata 与 migration head 无漂移；
4. 新索引和约束确实存在；
5. downgrade 是否支持由具体迁移风险决定，并在不支持时明确说明恢复方案。

## 7. 交付时报告

最终说明应包含：

- 实际运行的命令；
- 通过、失败和 warning 数量；
- 未运行的检查及原因；
- 需要人工验证的交互；
- 与本次改动无关的既有失败，不得冒充本次引入的问题。

## 8. Phoenix 验证

修改 Phoenix、OpenInference 或相关依赖时至少验证：

```bash
docker compose config --quiet
docker compose up -d --build phoenix backend
docker compose ps phoenix backend
docker compose logs --tail=100 backend
curl -fsS http://localhost:6006 >/dev/null
```

还应人工发起一次 Agent 对话，并确认：

1. Phoenix 的 `filmos-agent` 项目出现 LangChain/LangGraph Trace；
2. Trace 能看到模型调用、工具调用和耗时；
3. `PHOENIX_ENABLED=false` 时后端正常启动且不发送 Trace；
4. Phoenix 容器停止时，非 Agent 业务 API 不受影响；
5. Trace 中没有密码、JWT、Cookie、API Key 或数据库凭证。
