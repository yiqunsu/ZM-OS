# 0004 使用 Phoenix 观测 AI Agent Trace

状态：Accepted

日期：2026-07-22

## 背景

普通请求日志和异常堆栈无法完整回答 Agent 在一次对话中经过哪些 LangGraph 节点、调用了哪些模型和工具、各步骤耗时多少。排查 Agent 行为需要专门的 Trace 能力，但该能力不能侵入业务代码或影响业务可用性。

## 决策驱动因素

- 能查看 LangChain/LangGraph、模型和工具的端到端执行链路；
- 使用开放的 OpenTelemetry 和 OpenInference 数据模型；
- 支持本地自托管和独立 UI；
- 埋点与业务代码解耦；
- 采集端故障时业务仍能运行。

## 考虑过的方案

### 只使用结构化日志

基础设施最少，但难以重建嵌套的模型、节点和工具 Span，也缺少专门的 Trace 查询体验。

### 只使用 Sentry

适合异常和应用性能，但不是当前 Agent 步骤、Prompt 和工具链路的专门分析工具。

### OpenInference / OpenTelemetry + Phoenix

增加一个可观测性容器和数据治理成本，但能自动采集 LangChain/LangGraph Trace，并保持开放协议边界。

## 决策

- 后端使用 `arize-phoenix-otel` 注册 OpenTelemetry TracerProvider；
- 使用 `openinference-instrumentation-langchain` 自动观测 LangChain/LangGraph；
- Trace 通过 OTLP/HTTP 发送到独立 Phoenix 服务；
- Phoenix 使用独立持久卷，不写入 FilmOS 业务数据库；
- 所有埋点由 `PHOENIX_ENABLED` 控制；
- 初始化和导出失败不得阻止后端启动或改变业务结果；
- Phoenix 只负责 Agent 可观测性，不替代日志、Sentry 和业务审计。

## 结果与代价

### 正面影响

- 可以逐步查看 Agent、模型和工具执行过程；
- 可以分析耗时、Token、失败位置和行为差异；
- 业务模块不需要直接依赖 Phoenix；
- 以后可以在保持 OTLP/OpenInference 边界的情况下更换采集后端。

### 负面影响

- Docker Compose 增加 Phoenix 服务、端口和持久卷；
- Trace 可能包含 Prompt、回复和工具数据，需要访问控制与保留策略；
- Phoenix 和 instrumentation 版本升级需要兼容性验证；
- Trace 发送失败时可能丢失观测数据。

### 后续工作

- 生产部署固定 Phoenix 镜像版本；
- 生产环境配置认证、API Key、TLS 和 Trace 保留期；
- 为启用、禁用和采集端不可用场景补充测试；
- 评估 Prompt/工具字段脱敏策略。

## 相关资料

- [FilmOS 可观测性说明](../OBSERVABILITY.md)
- [Phoenix Docker 部署文档](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)
- [Phoenix OpenTelemetry 配置文档](https://www.arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-using-phoenix-otel)

