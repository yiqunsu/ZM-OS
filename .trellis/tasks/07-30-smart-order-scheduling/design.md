# 智能录单与规则排产设计

## 1. Runtime boundary

FastAPI 在 OpenClaw 前后承担业务编排。OpenClaw继续负责自由文本对话；录单提取和排产生成由后端显式路由到受控服务，输出统一 SSE UI 事件。OpenClaw不获得数据库或文件系统访问。

内部事件扩展为 `panel`、`form_update`、`schedule_plan`、`pending_confirmation` 和现有文本事件。浏览器只消费 FilmOS 事件，不解析 OpenClaw 原始响应。

## 2. Smart order flow

`POST /agent/chat` 接受文字以及最多一张图片（data URL）。后端限制 MIME、解码后大小和文件签名。录单意图或图片触发 `order_intake_service`：

1. 使用 OpenAI-compatible Chat Completions 调用文字模型或 `LLM_VISION_MODEL`；
2. 强制模型仅返回约定 JSON，并在后端做提取、类型归一和字段白名单；
3. 使用数据库候选列表匹配客户、产品与配方 ID；不确定时保持空值并由 Agent 追问；
4. SSE 打开订单表单并推送 `form_update`；
5. OrderForm 现有 dirty-field 机制保证人工编辑优先。

聊天下发复用现有 pending ChatMessage 机制，但新增运行时无关的 `submit_order_form` pending action。确认请求携带当前草稿；后端在同一事务内创建可选新配方、订单、成功消息，消费 pending 并关闭工作区，随后返回 `order_created` SSE。前端不再二次提交订单。右侧人工下发也调用同一原子草稿用例。

## 3. Scheduling engine

新增纯后端 `schedule_service`：读取待排订单、启用机器、机器类别/花纹和当前队列，构建可序列化方案。

生产签名：

```text
(formula/material, product_category, thickness, pattern)
```

换产成本采用字典序比较而非任意加权总分：配方变化、产品大类变化、厚度变化、花纹变化、宽度变化、幅宽闲置比例。候选键相同时比较按 kg 折算的预测队列负载，最后比较机器名称和 ID 以保证确定性。

订单按生产签名与创建时间处理。相同签名订单优先装入同一任务；合计宽度必须位于机器宽度范围内且不超过最大宽度。无法提取宽度或没有可行机器的订单进入 `unassigned`。

方案以 `SchedulePlan` 存入 PostgreSQL，保存输入订单、完整待排集合、启用机器集合、机器能力和未完成队列指纹，以及任务 JSON、未排原因、创建用户和状态。确认时加锁重新读取所有订单和机器；任一指纹变化都要求重新生成方案。通过后由 `apply_schedule_plan` 在一次事务中创建全部任务。订单编号使用 PostgreSQL 序列生成，避免并发创建或删除订单后复用编号。

## 4. Frontend workspace

ChatInterface 保留现有分栏模式：

- `order_form` 加载现有 OrderForm；
- `schedule_plan` 加载紧凑方案组件，展示机器任务、订单号、总宽度、原因和未排订单；
- 手机端在“对话/录入订单”或“对话/排产方案”间切换；
- 图片选择后在输入区显示真实缩略图，可移除，发送前转成 data URL。

## 5. Chat attachment lifecycle

附件状态只沿一条有明确所有权的路径移动：

```text
composer-selected
  -> optimistic-message
  -> server-committed-message + persisted-attachment
  -> history projection after refresh
```

- 读取图片成功后，前端在发起网络请求前把 `File` 从输入框移除，并把 data URL 交给乐观消息；输入框不等待 Agent 回复。
- 后端先验证并保存用户消息与 `ChatAttachment` 元数据，再发出 `user_message_committed` SSE 事件。事件包含服务端消息 ID 和附件公开元数据，不包含图片正文或文件路径。
- 前端收到该事件后用服务端消息 ID 和受保护的附件 URL 替换临时消息；随后识别成功或失败只影响 Agent 结果，不再改变输入框附件。
- 如果请求在服务端确认前失败，前端删除乐观消息并恢复原文字和 `File`；如果服务端已经确认，消息与附件保留。
- 历史接口直接返回附件元数据，刷新后使用同一受保护 URL 展示，不依赖模块变量、对象 URL 或 sessionStorage。

图片二进制不写入 PostgreSQL。`ChatAttachment` 只保存消息外键、不可猜测 ID、MIME、字节数和服务端生成的 storage key；文件写入后端专用持久卷。读取端点通过附件到消息、会话、用户的关联做授权。浏览器通过已认证的 Next.js Route Handler 同源代理读取，后端仍是授权权威。

会话删除时先收集附件路径，在数据库事务成功后清理文件。文件写入成功但数据库提交失败时立即补偿删除；不存在的文件返回安全 404。第一版每条消息最多一张 JPG/PNG，最大 5MB。

## 6. Safety and rollback

- 图片正文不进入日志、审计 prompt 或 PostgreSQL；日志和 SSE 只记录元数据。
- 附件目录使用独立持久卷并纳入生产备份；单机变为多实例前必须迁移到共享对象存储。
- 写操作均需显式用户点击确认。
- `AGENT_RUNTIME=langgraph` 仍可回退；新排产服务与运行时无关。
- migration 新增 SchedulePlan、ChatAttachment、聊天工作区字段和订单号序列，不改变现有订单/任务状态含义。

## 7. Production mutation safety refactor

人工看板与智能排产必须复用同一份生产兼容规则：机器启用、产品大类、花纹能力、幅宽范围和合并生产签名。共享规则位于后端 Service 层，前端只表达用户动作。

看板写入改成动作级原子用例：

- 移动订单：一个接口覆盖待排订单新建任务、并入任务、任务间移动、拆为新任务和退回待排；
- 移动任务：在后端锁定源/目标机器并重写两个队列位置；
- 同机重排：提交完整有序任务 ID 集合，后端校验集合未过期后一次重写；
- 状态迁移：新排任务为 `WAITING`，只允许 `WAITING -> PRODUCING -> DONE`，同一机器最多一个 `PRODUCING` 任务。

每个动作只提交一次事务，并返回提交后的完整看板快照。前端不再使用多个 `PUT` 拼装一个拖拽动作；失败时显示后端错误并重新加载权威快照。
