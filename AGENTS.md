# FilmOS Repository Instructions

本文件是整个仓库的开发入口说明。子目录中的 `AGENTS.md` 可以增加或收紧对应范围的规则。

## 开始修改前

1. 阅读 [meta/README.md](meta/README.md)；
2. 涉及业务、模型、状态或 API 时阅读 [meta/GROUND_TRUTH.md](meta/GROUND_TRUTH.md)；
3. 按改动范围阅读 [meta/ENGINEERING_RULES.md](meta/ENGINEERING_RULES.md)；
4. 开始实现和交付前阅读 [meta/TESTING.md](meta/TESTING.md)；
5. 改变长期架构选择前检查 [meta/decisions/](meta/decisions/)；
6. 修改日志、Sentry、Phoenix 或追踪配置时阅读 [meta/OBSERVABILITY.md](meta/OBSERVABILITY.md)；
7. 修改 `frontend/` 时同时遵守 `frontend/AGENTS.md`。

## 项目边界

- `frontend/`：Next.js UI 与登录层，不直连数据库；
- `backend/`：FastAPI 业务入口、SQLAlchemy Model、Service 与 API；
- PostgreSQL：业务数据权威来源；
- Alembic：数据库结构变更的正式渠道。
- Phoenix：可选的 AI Agent Trace 旁路，不是业务依赖。

## 不可绕过的规则

- 后端是业务规则的唯一权威执行者。
- 一次用户业务动作涉及多条数据时，必须作为一个原子用例完成。
- 订单状态、生产任务状态和关联关系必须保持一致。
- 新增或改变业务规则时，必须同步更新测试和相关长期记忆文档。
- 不提交秘密，不记录密码、Token、Cookie 或 API Key。
- 保留工作区中与当前任务无关的用户改动。
- 不为形式完整而提前增加 Repository 等空转抽象。

## 常用验证

后端（在 `backend/`）：

```bash
venv/bin/ruff check .
venv/bin/python -m pytest -q
```

前端（在 `frontend/`）：

```bash
npm run lint
npm run build
```

数据库和容器（在仓库根目录）：

```bash
docker compose exec backend alembic check
docker compose config --quiet
```

详细测试矩阵以 `meta/TESTING.md` 为准。
