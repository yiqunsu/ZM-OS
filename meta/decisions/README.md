# FilmOS 决策记录

本目录保存对系统长期演进有影响的 Architecture Decision Record（ADR）。ADR 的价值是保留“为什么这样选择”，而不是重复描述代码。

## 何时需要 ADR

以下情况通常需要：

- 改变前后端、数据库、鉴权或部署边界；
- 引入长期依赖的基础设施或外部服务；
- 改变关键领域模型、状态机或数据所有权；
- 在多个可行方案中作出有明显取舍的选择；
- 废弃一个已接受的长期决策。

局部重命名、小型重构、单个页面布局和容易撤销的实现细节通常不需要 ADR。

## 文件命名

```text
NNNN-short-kebab-case-title.md
```

编号递增且不复用，例如：

```text
0001-separate-frontend-and-backend.md
0002-postgresql-as-system-of-record.md
```

## 状态

- `Proposed`：正在讨论；
- `Accepted`：已经接受并应遵守；
- `Rejected`：讨论后未采用；
- `Deprecated`：不再推荐，但尚未被明确替代；
- `Superseded by NNNN`：已被另一项决策取代。

## 维护规则

- 使用 [TEMPLATE.md](TEMPLATE.md) 创建新记录。
- Accepted ADR 原则上保留历史，不通过删除旧文件“重写过去”。
- 决策变化时创建新 ADR，并更新旧 ADR 状态和链接。
- ADR 只记录重要上下文和取舍；执行细节放代码、测试或工程规范。

## 当前决策

| 编号 | 决策 | 状态 |
| --- | --- | --- |
| [0001](0001-separate-frontend-and-backend.md) | 前后端分离，FastAPI 为唯一业务入口 | Accepted |
| [0002](0002-postgresql-as-system-of-record.md) | PostgreSQL 作为业务数据权威来源 | Accepted |
| [0003](0003-snapshot-formula-on-order.md) | 订单保存配方快照 | Accepted |
| [0004](0004-use-phoenix-for-agent-observability.md) | 使用 Phoenix 观测 AI Agent Trace | Accepted |
