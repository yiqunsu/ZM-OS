# AI 助手接口、事件与前端契约

版本 1.0 · 目标协议 · 总入口：[PRD](../PRD.md)

## 1. 通用约定

新接口前缀 `/api/agent/v2`。浏览器走同源 Next.js 代理；FastAPI 独立验证当前身份和 Session 归属。JSON snake_case；日期 ISO8601 UTC；revision 为正整数。未知 JSON 字段默认拒绝，新增字段需版本兼容策略。

用户消息以 client_message_id 幂等；创建 Session 与按钮/确认命令使用 `Idempotency-Key`。调用方在发起一次逻辑动作时生成 key，网络重试复用，用户修改 payload 后使用新 key。Authorization、用户角色、lease_token、storage_key 均不在 action payload 中。

错误格式：

```json
{
  "error": {
    "code": "SESSION_BUSY",
    "message": "当前消息仍在处理中，请稍候。",
    "retryable": false,
    "details": {"active_run_id": "run_opaque"}
  },
  "request_id": "request_opaque"
}
```

读接口默认 limit=50、最大100，游标分页；事件补读最大200/页。上传、多图数量与文本上限见 PRD，后端与前端共同执行。资源未知和属于其他用户均404，不泄露存在性。

## 2. HTTP 接口矩阵

表中路径均相对于上述前缀。S=检查会话归属与 ACTIVE（纯读取可 ARCHIVED）；R=确认无 QUEUED/RUNNING Run；V=检查目标 revision；I=幂等。

| 方法与路径 | 入参要点 | 成功响应 | 校验与副作用 |
| --- | --- | --- | --- |
| POST /sessions | `{agent_type,title?}` | 201 SessionSnapshot | 仅 ORDER_INTAKE/SCHEDULING；I；创建会话，不启动 Run |
| GET /sessions | agent_type?、status?、cursor、limit | 200 列表页 | 仅本人 |
| GET /sessions/{sid}/snapshot | 无 | 200 SessionSnapshot | 授权，一致性快照含 event_cursor |
| POST /sessions/{sid}/archive | 无 | 200 SessionSnapshot | S/R/I；ARCHIVED |
| POST /sessions/{sid}/restore | 无 | 200 SessionSnapshot | 归属/I；恢复 ACTIVE，LEGACY 仍不可执行 |
| DELETE /sessions/{sid} | 无 | 202 `{status:"DELETING"}` | S/I；取消 Run，持久 GC；不等待文件 I/O |
| POST /sessions/{sid}/attachments | multipart：file、client_upload_id | 201 Attachment | S/R；私有 STAGED 上传；仅录单 |
| GET /attachments/{aid}/content | 无 | 200 图片 | 沿 session 授权；private/no-store |
| POST /sessions/{sid}/messages | SendMessage | 202 AcceptedMessage | S/R/I；原子接受输入并创建 Run |
| GET /sessions/{sid}/messages | cursor 或 before、limit | 200 Message 页 | 按 event_seq 稳定排序 |
| GET /sessions/{sid}/events | after、stream=true/false | 200 SSE 或 Event 页 | 会话授权；只发送安全事件投影 |
| GET /runs/{rid} | 无 | 200 RunSummary | 沿 Session 授权，未暴露租约 |
| POST /runs/{rid}/retry | `{expected_state_revision}` | 202 CommandResult | S/R/I；仅 FAILED，创建新 Run |
| GET /sessions/{sid}/items | status?、cursor、limit | 200 Item 页 | 仅录单；全部状态可回看 |
| GET /items/{iid} | 无 | 200 ItemSnapshot | 源图、draft、issues、revision |
| PATCH /items/{iid}/draft | `{expected_revision,patch}` | 200 ItemSnapshot | S/V；仅 ACTIVE，可与 Run 并行但受版本保护 |
| POST /sessions/{sid}/next-item | `{expected_state_revision,expected_next_item_id}` | 202 CommandResult | S/R/I；当前项必须空；激活 PENDING 并建 Run |
| POST /items/{iid}/select | `{expected_revision,expected_state_revision}` | 202 CommandResult | S/R/V/I；当前项空，PENDING/DEFERRED→ACTIVE 并建 Run |
| POST /items/{iid}/defer | `{expected_revision}` | 200 CommandResult | S/R/V/I；ACTIVE→DEFERRED，保留草稿 |
| POST /items/{iid}/close | `{expected_revision,confirmed:true}` | 200 CommandResult | S/R/V/I；未创建项→CLOSED，不删除图片 |
| POST /items/{iid}/confirm | `{expected_revision}` | 200 CommandResult | S/R/V/I；读取服务端草稿，创建正式订单 |
| GET /plans/{pid} | 无 | 200 PlanSnapshot | 同会话授权；含 stale/stale_reasons |
| PUT /plans/{pid}/draft | `{expected_revision,tasks}` | 200 PlanSnapshot | S/V；DRAFT 才能编辑，后端重新计算展示字段 |
| POST /plans/{pid}/replace | `{expected_revision}` | 202 CommandResult | S/R/V/I；显式授权替换，创建 Run |
| POST /plans/{pid}/close | `{expected_revision,confirmed:true}` | 200 CommandResult | S/R/V/I；DRAFT→CLOSED，清空当前指针 |
| POST /plans/{pid}/apply | `{expected_revision}` | 200 CommandResult | S/R/V/I；确认版本+输入指纹，原子排产 |
| GET /commands/{cid} | 无 | 200 CommandResult | 沿用户/会话授权，网络结果核实 |

没有 `/message/edit`、模型写入正式订单、给 Agent 任意 tool 名执行的通用 API。普通 `/orders`、`/production-tasks` 等业务入口继续存在，复用相同 Service。API 接收成功已含消息/命令 ID；确认请求超时尚未知 command_id 时，直接用原 Idempotency-Key 和原请求重试。

归档 Session 可读、可下载已有附件，不可写草稿/执行；DELETING 内容接口返回410，仅会话状态可查询删除进度。清理完成后404。对无权限用户仍统一404。

## 3. 消息、附件与工作项

### 3.1 SendMessage

```json
{
  "client_message_id": "client_uuid",
  "content": "这几张订单请逐张录入",
  "attachment_ids": ["attachment_a", "attachment_b"],
  "expected_state_revision": 3,
  "target_work_item_id": null
}
```

- attachment_ids 保序、去重拒绝，不静默丢图；全部必须为当前 Session 的 STAGED 附件，检查未过期。
- content 和 attachment_ids 至少一项非空。排单 attachment_ids 必须空，target_work_item_id 必须空。
- 录单纯文字补充携带当前 target_work_item_id 和 state_revision；不匹配返回409，不把旧页面输入套到另一张订单。
- 图片新建项，不以 target_work_item_id 指向当前草稿。已有当前项时图片只追加；同条附言只作为这些新图片的来源描述，不作为修改当前草稿的隐式指令。
- 多图消息接受具有批次原子性：任何一个附件失效则全部不绑定、不创建工作项和 Run；已上传 STAGED 文件保留可重试。
- 无当前项时选择首张新图对应项；已经有历史 PENDING 项时优先保留队列顺序，选择队首，而不是插队到新图。DEFERRED 不自动恢复。
- 录单纯文本无当前项：创建轻量 Run 引导上传/选择工作项，不凭空创建订单工作项。

```json
{
  "message_id": "message_opaque",
  "run_id": "run_opaque",
  "run_status": "QUEUED",
  "work_item_ids": ["item_a", "item_b"],
  "state_revision": 4,
  "event_cursor": 15
}
```

客户端先用 client_message_id 显示发送中，202 或 message.accepted 后变为已接受。失败后不生成另一个客户端 ID重发同一操作，除非用户明确改变内容。相同 key 不同文本/附件列表返回 IDEMPOTENCY_MISMATCH。

### 3.2 强类型截图提取 ScreenshotExtraction v2

完整字段定义见 [JSON Schema](order-extraction.schema.json)，完整响应示例见 [示例 JSON](order-extraction.example.json)。代码权威定义为 `backend/app/schemas/agent/order_extraction.py`，通过 model_json_schema() 生成模型提示中的约束。

| 字段 | 类型与规则 |
| --- | --- |
| schema_version | 必须为整数 2，外层和每笔订单都填写 |
| orders | 1～20 笔 OrderExtraction，按图内顺序 |
| customer_name / product_description / formula_raw / source_reference_no / notes | string 或 null，最多 2000 字符；单号不转数值，保留前导零 |
| width / thickness / quantity | 必须存在的测量对象，未知时内部字段 null |
| *.value | JSON number 或 null，严格拒绝数字字符串及 bool；正数≤1e12、最多12位小数、禁止 NaN/Infinity |
| width.unit | mm / cm / null |
| thickness.unit | μm / 丝 / null；um、c 等原文别名由模型规范为对应枚举，原文另存 |
| quantity.unit | m / kg / g / t / null，当前不推测数量单位 |
| *.source_text | 独立保存原始短语，string 或 null；不得作为数值兜底解析 |
| width/thickness.unit_source | EXPLICIT / INFERRED / UNKNOWN |
| width/thickness.inference_basis | 推测时为 1～300 字符非空依据，否则 null |
| warnings | 必填数组，最多20条文本，无问题时 [] |

所有字段必填，未知显式 null，拒绝未知字段。unit=null 时必须 UNKNOWN 且依据=null；INFERRED 必须提供数值/单位/依据，source_text 为不带单位的原始数字并与 value 相等，禁止改动原值或覆盖已写单位。其他未知字段不编造。

模型输出原始量纲下的数值和枚举单位，代码使用 Decimal 完成换算，最终表单统一 mm/μm/m/kg；原始提取不接收全部主数据、不输出内部 ID，不创建正式订单。单位推测继续生成 UNIT_INFERRED 提示，人工值和最新草稿保护不变。

模型请求当前使用 JSON object 模式，提示词附完整 Schema；后端严格验证失败时，仅向模型反馈字段路径及错误类型重试一次，不反馈原始错误值。再次失败不保存提取草稿。JSON 模式不等于供应商生成阶段的严格 Schema 保证；业务确认仍须校验完整字段。

旧 v1 提取证据保留，已识别草稿不重写。旧 quantity_raw 混合文本解析仅用于历史证据的兼容及定向修复；新识别不接受 v1 响应，也不会将 source_text 中的字符串强制转换成测量值。数据库草稿 quantity 仍为精确十进制字符串，和模型 JSON 数字输出属于不同层的契约。

### 3.3 OrderDraft v1 / FieldIssue

```json
{
  "schema_version": 1,
  "customer_id": null,
  "product_id": null,
  "spec_params": {"宽幅": "425mm", "厚度": "118μm"},
  "quantity": "7500",
  "unit": "m",
  "formula_mode": "none",
  "formula_id": null,
  "extra_notes": ""
}
```

quantity 是精确十进制字符串或 null，unit 为 m/kg/null，未识别不可默认 kg。宽幅/厚度允许未完整草稿，但确认必须满足业务验证；附加 spec 字符串每项≤2000字符、≤30项，禁止 status/order_id 等进入 draft。formula_mode 仅 none/existing，existing 需兼容 formula_id。选择产品变化时服务端重新检查配方，不沿用不兼容配方。

PATCH 只允许上述可编辑字段，spec_params 的 patch 以键合并；显式 null 删除可选项，缺省不改变。所有补丁都更新 provenance 并重算 issues/revision，禁止盲目 `dict.update` 任意模型对象。

```json
{
  "code": "CUSTOMER_AMBIGUOUS",
  "field": "customer_id",
  "severity": "BLOCKING",
  "message": "找到多个客户，请选择。",
  "candidates": [{"id":"customer_a","label":"华兴公司"}]
}
```

severity=BLOCKING/WARNING；code 固定集合：CUSTOMER_MISSING、CUSTOMER_UNMATCHED、CUSTOMER_AMBIGUOUS、PRODUCT_MISSING、PRODUCT_UNMATCHED、PRODUCT_AMBIGUOUS、SPEC_MISSING、SPEC_UNIT_UNKNOWN、QUANTITY_INVALID、UNIT_UNSUPPORTED、FORMULA_INCOMPATIBLE、INPUT_CONVENTION_VIOLATION、NO_ORDER_CONTENT。候选≤10，后续搜索分页获取。m 订单允许创建，以 WARNING 提示当前不可排产，不当作录单阻塞问题。

### 3.4 SessionSnapshot

返回 session 基本字段、逻辑 SessionState、active_run、当前 Item/Plan、待处理数量、messages 第一页、recent_run_results、event_cursor。recent_run_results包含当前消息页范围内尚无最终Message的失败/取消Run（含终态事件seq、原输入ID、错误及是否可重试）；不能只查询active_run，否则刷新会丢失失败卡。历史分页同样返回所覆盖时间线内的Run失败摘要。服务端在同一短事务内锁定Session并读取快照；所有v2写入共享该锁，确保游标与快照一致，响应前释放锁。后续 GET events 从该 cursor 补读；不能先取得游标再用另一时刻的数据拼快照。

附件 DTO 仅含 id、mime_type、byte_size、width_px、height_px、position、available；不含 storage_key 或原始 data URL。当前项恢复从 Item 查询，不从历史 presentation 反向还原草稿。

## 4. 排产草案与确认

PlanSnapshot 返回 id、status、revision、tasks、unassigned、stale、stale_reasons、created_at、applied_result。每个任务字段：`draft_task_id`（草案内部稳定标识）、machine_id、order_ids、position、machine_name、order_nos、reason_codes、summary；展示字段均由服务端生成，客户端只提交 machine_id/order_ids 与列表顺序。

UnassignedOrder 包含 order_id、reason_code、message；reason_code 如 NO_COMPATIBLE_MACHINE、WIDTH_UNSUPPORTED、PATTERN_UNSUPPORTED、SPEC_INCOMPLETE、WEIGHT_CONVERSION_UNAVAILABLE。Order ID 在同一草案只能出现一次，安排集合与未安排集合不能重叠或漏掉输入订单。

确认只接受服务端对象 ID 与 expected_revision，不接受任意完整订单/生产任务作为执行参数。手动编辑必须先保存，再取得 revision，再确认。草稿可在模型运行期间手动保存，模型写入旧版本必须冲突；确认/切换等控制动作要求没有开放 Run。

对 APPLIED Plan 或 CREATED Item，重复确认先查幂等记录；即使用新 key，后端返回已存在的正式结果，且不再写第二条成功消息/审计。新 key 的 Command 可记录 returned_existing=true 并引用原结果。任何真正的新业务写入仍必须同时检查状态、revision、权限和指纹。

## 5. SSE 事件协议

### 5.1 事件封装

```text
id: 42
event: message.completed
data: {"id":"event_opaque","session_id":"session_opaque","seq":42,"kind":"message.completed","schema_version":1,"run_id":"run_opaque","message_id":"message_opaque","work_item_id":"item_opaque","created_at":"2026-09-11T02:00:00Z","payload":{"role":"assistant","text":"订单创建成功，是否处理下一张？","attachment_ids":[],"presentation":{"schema_version":1,"actions":[]}}}

```

SSE id 为 Session 内 seq，初次用 `after`，重连支持 Last-Event-ID；若两者都提供必须相同，否则400。心跳为 SSE 注释，无 seq，不持久化。事件已提交才可推送，客户端按 `(session_id,seq)` 去重；浏览器切换 Session 后不能将旧流追加到新会话。

API 以短查询轮询 session_events（初始每0.5秒，空闲退避），无需 worker 与 API 共享进程内队列；后续可加通知优化，但数据库补读永远是恢复路径。不能为整个 SSE 连接持有数据库事务。禁止代理缓冲，处理认证过期、背压与浏览器重连。

### 5.2 核心 payload

| kind | 必须包含的 payload | 前端用途 |
| --- | --- | --- |
| message.accepted | role、text、attachment_ids、client_message_id | 清理输入、绑定真实消息 |
| run.queued / started | trigger_kind、work_item_id? | 禁用输入、显示等待/执行 |
| run.progress | stage、label | 识别/匹配/生成阶段提示 |
| admittance.decided | decision、reason_code | 安全阶段信息，可不展开 |
| work_item.* | item_id、status、revision、queue_position | 更新列表与当前项 |
| recognition.* | item_id、recognition_status、issue_codes | 更新识别状态，不发送图片正文 |
| draft.updated | item_id、revision、changed_fields | 重新拉取权威草稿，不能直接覆盖本地 dirty 字段 |
| plan.* | plan_id、revision、status、summary | 重新读取草案或展示提交结果 |
| tool.started | tool_call_id、tool_name、label | 工具进度 |
| tool.succeeded / failed / abandoned | tool_call_id、summary、error_code? | 安全结果/错误，不发送任意原始参数 |
| assistant.delta | chunk_index、text | 本 Run 临时文字追加 |
| message.completed | role、text、attachment_ids、presentation | 替换临时文字为不可编辑定稿 |
| run.succeeded | outcome、output_message_id | 结束忙碌 |
| run.failed / cancelled | error_code、message、retryable、partial_output_discarded | 错误卡，保留用户输入和已保存草稿 |
| command.accepted | command_id、kind、result | 恢复按钮结果 |
| session.state_changed | state_revision、active_work_item_id、active_plan_id | 刷新工作区选择 |

### 5.3 文本流式输出与恢复

只在无工具的compose_response节点流式发送最终解释；Main Agent工具规划和中间模型文字不作为聊天回复，不能一边展示“最终回复”一边继续执行业务工具。模板回复直接落定稿Message。工程初始每100ms或256字符合并一次（取先达到者），以 assistant.delta 追加持久事件后再发送，避免逐 token 一次数据库事务。流式结束后完整 Message 与 message.completed/Run 终态原子提交。

客户端收到 message.completed 以完整文本替换临时内容，不重复拼接。Run 失败时临时文本显示为“未完成”或收起，不伪装为已定稿 Message，也不进入下一轮模型正常历史。事件保留可诊断的输出片段，整段 Message 尚未存在。

重连按 cursor 补事件即可恢复片段或最终消息。新页面优先 snapshot；Run 已结束时无需重放所有 delta，只加载定稿/失败卡。事件首期保留到 Session 删除，不做任意部分 TTL 裁剪；如果未来增加裁剪，先增加410 CURSOR_EXPIRED与快照重置协议。

## 6. 结构化消息按钮

```json
{
  "schema_version": 1,
  "actions": [{
    "kind": "NEXT_ITEM",
    "label": "处理下一张",
    "target_id": "item_b",
    "expected_state_revision": 8,
    "expected_revision": 1
  }]
}
```

ActionKind：NEXT_ITEM、SELECT_ITEM、RETRY_RUN、OPEN_AGENT、OPEN_WORKSPACE、REPLACE_PLAN。业务创建/排产确认固定放在右侧工作区，不在模型自然语言中解析执行。

按钮由服务端根据已提交状态构造；action 不是凭证，前端不能根据其中 URL 执行任意请求。按 kind 映射固定 API；点击时生成/复用 Idempotency-Key。历史 NEXT_ITEM 按钮的 target 已不是队首或 state_revision 过期时返回 ACTION_STALE，刷新展示当前按钮，不处理错误项。

OPEN_AGENT 只导航至对应入口，用户点击后才创建新 Session；不自动转交历史、草稿或附件。无下一项时不生成 NEXT_ITEM。多个会话/页面重复点击由服务端幂等与状态规则兜底。

## 7. 错误码与恢复矩阵

| HTTP / code | 场景 | 恢复方式 |
| --- | --- | --- |
| 401 AUTH_REQUIRED | 身份过期 | 重新登录/刷新认证后补读，不泄露令牌 |
| 404 RESOURCE_NOT_FOUND | 不存在或越权 | 返回列表，不显示其他用户信息 |
| 409 SESSION_BUSY | 有开放 Run | 不接受新消息；等待或刷新状态 |
| 409 SESSION_STATE_CHANGED | 当前项已切换 | 保留输入，加载最新项后确认发送目标 |
| 409 DRAFT_REVISION_CONFLICT | 草稿被修改 | 拉取新草稿，保留本地 dirty 内容供比较 |
| 409 PLAN_STALE | 订单/机器/队列变动 | 重新生成并核对 |
| 409 IDEMPOTENCY_MISMATCH | 同 key 不同请求 | 修正客户端，不重用 key |
| 409 ACTION_STALE | 历史按钮目标/版本失效 | 刷新当前操作按钮 |
| 409 WORK_ITEM_CLOSED | 已放弃不能继续 | 上传新截图建立新项，不复活 CLOSED |
| 422 INPUT_INVALID | 格式/类型/业务字段不合要求 | 指出字段修正 |
| 422 IMAGE_NOT_ALLOWED | 排单 Session 图片输入 | 移除附件或进入录单入口 |
| 413 ATTACHMENT_LIMIT | 大小/张数/像素超限 | 分批或缩小图片 |
| 410 SESSION_DELETING | 删除处理中 | 等待清理，不恢复执行 |
| Run: MODEL_UNAVAILABLE / MODEL_TIMEOUT | 模型失败 | 新 Run 重试，保留来源与草稿 |
| Run: ADMITTANCE_INVALID_RESPONSE | 范围分类结果无效或截断 | 保留输入和草稿，由用户发起新 Run 重试 |
| Run: EXTRACTION_INVALID | 结构修复仍失败 | 重试/人工填写/暂放 |
| Run: QUEUE_TIMEOUT / WORKER_LOST / RUN_TIMEOUT | 等待/执行超时 | 终态失败，新 Run 重试 |
| Run: GRAPH_VERSION_UNAVAILABLE | 领取时部署版本不可执行 | 使用当前版本明确重试；不静默混用版本 |

## 8. 前端状态实现约束

共用 SessionShell、MessageList、RunStatus、ActionRenderer；OrderIntakeWorkspace 和 SchedulingWorkspace 独立。领域 DTO 集中管理，后端 Schema 与前端类型同变更，建议 CI 对 OpenAPI 导出的契约做差异检查。

前端区分 server snapshot、本地未保存 form edit、临时 streaming text。收到 draft.updated 时先比较 revision；dirty 表单提示服务端变化，用户明确加载/重新应用，不能静默整表覆盖。当前 Run 运行中可以本地编辑草稿和保存，但发送新消息、切换/关闭项、正式确认禁用。

切换路由、关闭标签页不取消 Run。返回后重新授权、加载 snapshot 与 cursor，恢复当前项、暂放列表、Run 状态和可操作按钮。SSE 只是状态同步传输，不是启动或完成执行的权威来源。


## 9. 重试的输入边界

只允许重试该Session最近一次FAILED Run，且目标工作项仍为当前ACTIVE项、SessionState版本一致；旧历史失败按钮返回ACTION_STALE。重试复用旧用户Message引用，创建新的Command与Run，不修改旧消息/旧Run；input_event_seq取本次重试Command事件边界，context_snapshot记录原始输入ID及当前草稿版本。不得把别的工作项消息混入当前对象。

RETRY复制原始业务动作类型与必要参数到新Run.config_snapshot中的retry_intent（固定Schema），不复制凭证、租约或旧工具结果状态。原Run已生成草案或完成识别时优先解释当前结果，不重复生成。若失败的是替换方案，旧plan_id/revision授权仍须匹配；版本变化返回冲突，要求重新点击替换按钮。任何已成功正式订单/排产结果都通过对象状态返回，不因重试模型重新执行业务确认。


## 10. 持久JSON与枚举的补充契约

- `Session.state`：ORDER_INTAKE为`{schema_version:1,last_question:null或字符串,last_question_work_item_id:null或当前项ID}`；SCHEDULING为`{schema_version:1,last_question:null或字符串}`；LEGACY仅迁移信息。客户端不得直接PUT这个JSON，Service根据已提交动作维护。
- `Run.config_snapshot`：schema_version、model_id、vision_model_id、admittance_model_id、prompt_versions（名称到内容hash）、skill_versions、tool_registry_version、limits（model_timeout_seconds、run_timeout_seconds、max_main_calls、max_tools、context_tokens）、retry_intent（可空）。模型地址和凭证不进入快照，配置通过服务端registry解析。
- `Run.context_snapshot`：schema_version、message_ids、work_item_id、work_item_revision、plan_id、plan_revision、input_event_seq、truncated_message_count、usage_complete。ID/revision可空但必须对应类型；不复制会话其他项完整草稿。
- `provenance`：草稿字段路径到`{source:USER或EXTRACTION或MATCH,source_message_id,source_attachment_id,source_run_id}`；不用模型声称的confidence替代真实校验。原图新识别不覆盖USER来源值。
- `SchedulePlan.input_fingerprint`：schema_version、pending_order_ids_hash、order_content_hashes（按订单ID）、active_machine_ids_hash、machine_capability_hashes、unfinished_queue_hashes。规范化排序与内容hash由唯一后端函数定义，数据库时间戳不是唯一过期依据。
- `Command.result`：schema_version、command_id、kind、run_id（可空）、state_revision、item_id/plan_id/order（按kind）、returned_existing（boolean）、event_cursor。API响应与落库结果相同。
- `Audit.result`：schema_version、outcome/error_code（Run）、order_id/order_no（建单）、task_ids/task_count/order_count（排产）、returned_existing（如适用）；不保存文本。
- `run.progress.stage`：ADMITTANCE、QUEUED_ACK、EXTRACTING、MATCHING、DRAFTING、READING_BOARD、GENERATING_PLAN、EXPLAINING；只用于显示，不替代RunStatus。
- `admittance.decision`：ALLOW、CLARIFY、OUT_OF_SCOPE；reason_code：IN_SCOPE、NEEDS_TARGET、MISSING_INPUT、WRONG_AGENT、UNSUPPORTED_OPERATION。分类失败是Run错误，不输出未定义decision。两个Agent共用JSON模式与显式Schema约束；仅丢弃模型额外附带的reason解释字段，不改变decision。其他未知字段、非法枚举、截断回复和工具调用仍拒绝，并返回ADMITTANCE_INVALID_RESPONSE；解释字段不进入路由事件。

SessionState引用、草稿revision、Event seq和GraphState各自独立。实现不得为了少写DTO而用任意dict穿过所有层。

草案任务draft_task_id对未改变分组保持稳定，合并/拆分生成新ID；它只是展示键，不能作为实际生产任务ID。所有接收的tasks按订单覆盖集合重新验证，服务端不信任旧展示ID。

### 实施补充：快照和历史分页

会话列表按 updated_at、id 倒序排列，cursor 为不透明游标。消息支持前向 cursor 或后向 before，两者不可同时指定；页内始终按 event_seq 正序显示。SessionSnapshot 的 work_items 为首批 100 项，另返回 active_work_item 与 next_work_item，确保当前项/队首不因分页缺失；剩余历史通过 items 接口加载。

### 旧协议退役（2026-09-12）

旧 `/api/agent` 会话、聊天、附件和确认接口，旧 `/api/schedule-plans` 接口，以及 `/api/agent/v2/history/*` 均已移除，返回 404。前端不再提供 `/agent-history`。新版只接受两个专用类型，旧 Session ID 不可读取或继续执行。

### 同图多单（2026-09-12）

WorkItem 新增 source_order_index（1～20），queue_position 表示截图顺序。列表按二者排序，分页游标为 `queue_position:source_order_index`，初始 `0:0`，确保一张图内分页不丢单。识别返回 orders 数组并原子生成各单草稿；幂等工具调用重放不再创建副本。`SELECT_ITEM` 可原子暂存当前项并激活目标项；目标已识别时直接返回 200、run_id=null，未识别时入队返回 202。`NEXT_ITEM` 同样跳过已完成识别，不自动确认任何正式订单。

排单范围判断：普通“帮我排单 / 请帮我排单 / 安排一下生产 / 给我排一下”固定语义为 ALLOW + IN_SCOPE + GENERATE，缺少用户提供的订单/机器信息不构成澄清条件，生成流程自行读取。查询、否定生成和明确正式执行请求分别保留 QUERY / EXECUTE_REQUEST 语义；已有草案仍由生成服务要求替换确认。


## 录单工作台协议（2026-09-13，当前前端）

| 接口/字段 | 当前行为 |
| --- | --- |
| POST /sessions/{sid}/recognize | 同 SendMessage 请求形状，content 必须为空、attachment_ids 为1～5张；client_message_id、expected_state_revision、target_work_item_id 和接收幂等规则不变。只允许 ORDER_INTAKE，202 后从快照/SSE读结果。 |
| POST /items/{iid}/recognize | `{expected_revision}` + Idempotency-Key；只重试尚未成功识别且未结束的图片项，202创建 RECOGNIZE_ITEM 命令及 RESUME_ITEM Run；已成功项返回 ACTION_STALE。 |
| confirm / defer / close 的 advance | 可选 bool，默认 false；工作台传 true，后端在同一事务选下一笔 PENDING+SUCCEEDED 为 ACTIVE。保留 DEFERRED，等用户手动回来；没有下一项时清空当前项。重复确认不再次推进。 |
| WorkItem.created_at / customer_name / product_name | 创建时间与最新草稿关联基础数据的展示投影；无匹配对象则名称为 null，前端用通用名称；不新增冗余标题列。 |
| snapshot.work_item_counts | 全 Session 按内部状态统计，避免第一页100项造成计数错误；列表继续用 queue_position:source_order_index 游标。 |
| Session.image_count / order_count | 会话列表投影，分别为绑定图片数和识别成功的独立订单工作项数；不是正式订单数。 |
| Run.work_item_id / config_snapshot.intake_workbench | 前者用于图片级进度；后者由服务端设置，决定固定图片识别路径和后续图片接续，不接受客户端覆盖。 |

工作台不读取 Message 文本来驱动流程，不渲染助手思考、delta 或 NEXT_ITEM 按钮。已有消息/事件仍保存以支持审计和重连；排单使用结构化选单动作和草稿看板，见[智能排单看板](scheduling-workbench.md)。表单提交失败保留本地值，保存成功后才按新 revision 发确认命令；正式确认成功但刷新失败时显示成功并重试读取。


### 字段核对和语义匹配（2026-09-13）

ScreenshotExtraction v2 保留 `context_text: string|null`（最长2000），用于群名/发送者原文。每单增加 `customer_match` 和 `product_match`；存储模型允许省略以兼容旧v2，当前视觉请求的动态模型要求两个字段显式存在，未知为null。非空选择包含 candidate_id、严格数值 confidence/runner_up_confidence（0～1）、原文 evidence 和简短 reason，禁止额外字段。数值和单位约束不变。

`entity_matching.extraction_schema(catalog)` 根据本次数据库候选生成ID枚举（单候选为const，空候选仅允许null）；名称和产品大类在用户数据上下文中传入，不拼进自然语言规则。视觉传输继续使用提供方兼容的 `response_format=json_object`，Schema作为输出说明传入，再由同一个Pydantic模型严格验证；不宣称提供方支持原生约束解码。静态 [Schema](order-extraction.schema.json) 描述兼容存储形状，候选ID枚举仅在每次请求动态绑定。

候选每类最多50条、序列化UTF-8最多8000字节，超限的类别进入 catalog_manual_fields 并提示手选；已有唯一明确名称匹配仍可应用。有效语义建议要求原文引用、评分≥0.90且领先次选≥0.15，拒绝同名歧义，写入前再次查库。ENTITY_INFERRED warning保存 confidence/evidence/candidates，产品语义匹配把原始描述写入 extra_notes（人工备注仍优先）。没有新HTTP接口或数据库表。

格式问题最多重试一次。第二次仅匹配字段无效时，清空具体无效字段，保留其他有效选择、规格和数量；其他提取结构无效则不保存结果。`run.progress` 的 RECOGNITION_ERROR 阶段记录安全 code 和 attempt：NOT_CONFIGURED、TIMEOUT、CONNECTION_ERROR、HTTP_ERROR、RESPONSE_INVALID、OUTPUT_TRUNCATED、JSON_INVALID、SCHEMA_INVALID。终止时 recognition.failed/last_error_code保留失败码（其他结构无效为EXTRACTION_INVALID）。MATCHING阶段与 context_snapshot.entity_matching 记录每单每字段 ACCEPTED、NO_CONFIDENT_MATCH、INVALID_CANDIDATE、LOW_CONFIDENCE、EVIDENCE_MISMATCH、AMBIGUOUS_NAME，不保存完整模型响应。旧 MATCHING_UNAVAILABLE 属于已停用的独立文本匹配路径，不再产生；历史记录可继续读取。

前端核对说明继续使用带Portal的锚定浮层，避免卡片overflow/堆叠上下文裁剪，支持边缘避让、Escape关闭和焦点返回，归档只读也可查看。


### 截图日期与展示编号（2026-09-13）

工作项快照、详情与分页读取增加 `source_uploaded_at`（附件上传时间，ISO datetime）、`source_day`（Asia/Shanghai 日历日期，YYYY-MM-DD）、`source_day_position`（正整数）。后端对本人所有录单Session中至少一笔非 CLOSED 工作项的附件，按日期及有效归档状态分别做窗口排名，先排名后分页，避免分页或识别跨天造成编号错误。同图所有订单共享编号，纯 CLOSED 来源不返回展示信息。队列 queue_position 和 source_order_index 保留原值用于持久定位，不能用展示编号调用业务命令。

前端日期新到旧、日内上传时间早到晚排列，源图标题、识别进度与放弃提示复用同一编号；未识别使用状态而非“0笔订单”。快照事件版本改变时丢弃额外分页缓存，当前项由快照独立返回，历史只读选中项重新读取，防止保留旧编号。后续页可再次加载；不因重新排序覆盖未保存草稿。无数据库迁移。

### 统一截图列表与归档（2026-09-13）

- `POST /intake/workspace`，带Idempotency-Key：返回 `{session}`。用户锁下复用ACTIVE录单Session，无可复用时创建；没有前端新建录入记录入口。
- `GET /intake/screenshots?tab=pending|created|archived&cursor=...&limit=20`：返回 `{screenshots, counts, next_cursor}`。每页1～50张完整截图，每张包含全部非CLOSED订单，列表按筛选展示；counts涵盖全用户未归档WorkItem状态及ARCHIVED订单数。只授权本人ACTIVE/ARCHIVED的ORDER_INTAKE，排除DELETING及纯CLOSED来源。
- 截图分组字段：id、source_day、source_uploaded_at、source_day_position、source_archived、screenshot_revision、busy、running_item_id、items。items继续为工作项DTO，含session_id和上述source元数据。分页游标编码日期、上传时间、附件ID，先全集合排名后筛选及分页；不使用会变化的展示编号定位写操作。
- `POST /intake/screenshots/{aid}/archive|restore`，带Idempotency-Key，体为 `{expected_revision: 非负整数}`；返回 `{attachment_id, archived, revision}`。匹配附件版本，并在Session锁下要求无开放Run。幂等重放返回原结果；过期版本为SCREENSHOT_REVISION_CONFLICT。暂存当前ACTIVE草稿、更新附件、Session版本、事件及命令在同一事务提交。
- 归档截图的草稿修改、确认、选择、识别、放弃均拒绝SCREENSHOT_ARCHIVED；恢复后再处理。Session状态ARCHIVED也构成有效截图归档。恢复旧归档Session中的一张时，仅恢复该图，其他附件转为显式归档；消息、图片、草稿和正式订单不移动或重写。
- 归档动作使用既有session.state_changed事件（action=ARCHIVE_SCREENSHOT/RESTORE_SCREENSHOT、source_attachment_id），无需新增SSE事件类型；前端同时在15秒刷新中感知其他旧Session变化。完整会话接口继续用于排单/运行底座，不在录单界面显示为记录管理。


## 智能排单看板协议（2026-09-13）

新增 `POST /scheduling/workspace` 与 `POST /sessions/{id}/schedule`，前缀均为 `/agent/v2`。后者接收 expected_state_revision 和非空、唯一 order_ids，带 Idempotency-Key，返回既有 accepted Message/Run DTO。请求哈希绑定选单范围；类型错误、范围变化、已有草稿分别为 WRONG_AGENT_TYPE / ORDER_SELECTION_STALE / PLAN_EXISTS。可信按钮动作跳过意图分类，仍完整保留持久化、Worker 租约和事件边界。

GET plan 返回 input_order_ids 与 created_by_run_id；前端可将该 Run 的最终 Message 作为辅助说明，流程只依赖结构化状态。PUT draft/replace/close/apply 沿用既有契约。自动保存期间互斥，确认前提交已保存的最新 revision；后端对选中订单和全部机器实际队列重新验证。完整交互与指纹范围见[智能排单看板](scheduling-workbench.md)。


## 米数排产契约（2026-09-15）

- GET/PUT Plan 响应增加 load_basis，枚举 TASK_COUNT / WEIGHT_KG；数据由后端选单与真实机器队列确定。
- task.total_quantity_kg 为 number|null，未知米数重量为 null；task.total_quantity_m 为 number，米数任务保留原长度，重量任务为0。不以这两个指标改写订单数量。
- 米数订单之间允许按生产签名与合计幅宽合单；米数与重量混合任务返回409；Agent草稿修改为 INPUT_INVALID。各人工生产入口执行相同规则，失败保持原队列和订单关联。
- 旧规则草稿读取为 stale，修改/下发被拒绝。重新生成沿用已确认的订单范围，旧草稿在成功生成后再被替换。


## 正式生产状态确认（2026-09-15）

订单管理复用 `PUT /api/production-tasks/{task_id}`，不通过普通OrderUpdate直接改生产状态。支持WAITING→PRODUCING→DONE，以及DONE→PRODUCING恢复；不能直接标PENDING或跳过开始生产。两类业务角色都可操作，前端先选择后确认并列出同任务订单。

ProductionTaskUpdate新增可选 `expected_status`（TaskStatus）、`expected_updated_at`（ISO8601时间）、`expected_order_ids`（ID数组）。两个前端入口均携带当前快照的保护字段；后端在排产事务锁内核对，任何不一致返回409。TaskRef及ProductionTaskOut增加updated_at供客户端确认保护；状态发生变化会更新此时间。旧状态确认不能跨过一次完成/恢复循环再次生效。

恢复保留原任务ID、原订单关联、数量单位，原子同步整组订单PRODUCING并置于原机器未完成队尾。机器启用、当前能力、合单规则和无其他生产中任务均需通过，否则不改变任何状态。普通待排订单仅可先排单；撤回待排继续使用既有看板原子操作。无需DDL。
