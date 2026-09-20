# Agent 与工作区代码检查 · 2026-09-13

范围：development 当前工作区的 Agent 编排、模型输入输出、订单工作项/排单/会话 Service、附件路径、前端助手状态和设计文档。此次是静态依赖检查与定向回归，不等于全面安全审计或真实模型准确率验收。

## 当前架构判断

保留 Next.js → FastAPI → PostgreSQL Run 队列 → Worker → 两个专用 Graph 的结构。后端持有权限与正式业务确认，前端复用原有订单表单；这些边界合理，暂时不需要拆微服务或引入 Repository 层。

## 已处理的问题

| 问题 | 影响 | 本次处理 |
| --- | --- | --- |
| 首次快照失败后只能恢复数据、不能建立事件连接 | 后续刷新成功仍显示未连接，流式消息只能等快照 | useAgentSession 在成功刷新时尝试建立缺失连接，保留单连接、游标去重和会话切换清理；新增浏览器回归 |
| Agent 从旧 order_intake_service 导入私有模型函数 | 模型通信与已退役的全量候选匹配、data URL 入口混杂，维护者容易误改旧路径 | 删除没有业务调用者的旧识别入口、匹配与校验；保留有用部分到 agent/model_transport.py，使用明确公开函数名 |
| 排单回复混入录单专用提示词 | 排单受到“只能说明订单草稿”的不相关限制 | 共用 COMPOSE 仅保留事实/权限规则，ORDER_COMPOSE 和 SCHEDULING_COMPOSE 分别负责业务说明，分别记录版本 |
| 调用预算在注册表、Graph、工具服务中重复写死 | 修改快照中的上限未必改变实际行为 | agent/limits.py 统一定义现有上限，快照和执行共用；补充总模型次数和文本字节预算的快照字段 |
| 公共 Prompt 版本函数放在录单能力模块 | 配置依赖业务 Graph 导入；录单子类重复父类初始化 | 版本函数归 prompts，注册表按需加载两类 Graph；OrderCapabilities 复用父类初始化 |
| 文档仍描述旧会话只读、识别 v1、已失效图片配置 | 实现和开发依据不一致 | 更新当前架构与 README；历史部署记录保留并明确其历史属性 |

模型 HTTP 的供应商参数和截断拒绝测试保留；删除四项针对退役入口的测试，补上五项实际图片上传校验测试，不用测试数量替代有效覆盖。

## 后续优化落实（2026-09-13）

前三项建议已按用户确认的方案实施：

1. **AgentShell 状态拆分。** Shell 从约830行缩至407行，保留布局和工作项协调。useAgentComposer 管理输入、图片上传缓存、发送幂等与不确定结果重试；useSessionDirectory 管理首页列表、创建、归档和删除；AgentConversation 管理消息分页与展示；AgentComposer 负责输入区。所有命令共用 useAgentOperation 的同步互斥。父组件继续按 Session ID 挂载，移动端仅切换显示，不卸载草稿。
2. **强类型识别直接转换草稿。** Schema 不再含 normalization_input()。order_extraction_normalizer 直接使用校验后的数值和单位进行 Decimal 换算，原文不参与重新解析，单位推测依据独立保留。已知规格独立换算，不因另一规格缺失而停止。历史 v1 解析隔离到 legacy_order_extraction，新 Graph 仍只接收 v2。
3. **Service 按职责拆分。** agent_query_service 承担授权查询、分页及一致快照，agent_projections 承担响应字段投影；Router 不再拼装会话/消息/工作项查询。order_matching_service 负责已有对象匹配，order_draft_service 负责草稿校验与补丁规则，order_recognition_service 负责整图识别应用，order_intake_item_service 保留工作项操作和正式确认。新拆出的匹配、校验和识别模块不提交事务；创建订单、状态、消息与审计仍由同一用例提交。

## 仍可后续演进

SSE 事件种类和若干 DTO 仍由前后端分别维护。后续可从后端契约生成类型/事件清单，避免新增事件时前端漏订阅；该项不在此次用户确认的三项优化范围内。

实际模型意图和识别质量仍应采用固定样本集评估，不能只靠模拟模型测试。

## 本轮验证

首次检查后端 230 项、浏览器 19 项、全栈 3 项通过；后续重构的验证结果记录在实施进度中。Ruff、前端 lint/build、Compose 配置与 diff 检查通过。测试覆盖协议恢复、模型传输、附件、预算上限、录单/排单事务及端到端确认。交付结果与本地部署记录见[实施进度](implementation-status.md)的本轮条目；未进行生产部署或修改数据库结构。
