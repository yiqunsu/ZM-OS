# AI 助手实施、迁移与验收计划

版本 1.0 · 目标计划，实施进度见 [implementation-status.md](implementation-status.md) · 总入口：[PRD](../PRD.md)

## 1. 设计冻结时的代码与目标差距

下表记录设计冻结时的 development 工作区基线，不代表如今的实现状态或运行中服务器状态。已落地能力和剩余工作以 [实施进度](implementation-status.md) 为准。

| 范围 | 当前代码 | 目标 |
| --- | --- | --- |
| 入口 | `backend/app/agent/runner.py` 按关键词/工作区分流 | 固定 Session 类型选择两个 Graph |
| 消息执行 | POST 返回的 SSE generator 驱动执行 | 202 接受、持久 Run 队列、独立 GET SSE |
| 排单图 | `agent/scheduling.py` 有三个受限工具和有界循环 | 保留能力边界，增加范围判断、替换授权、统一 Run/事件 |
| 录单（重构前） | 原单次提取服务已退役；当前模型传输位于 agent/model_transport.py | 单图原始提取、受控匹配、工作项草稿和独立 Graph |
| 附件 | `ChatAttachment.message_id` 唯一，一条消息一张图 | 暂存上传、多图消息、每图一个工作项 |
| 状态 | `chat_sessions.workspace_state` 混合草稿 | SessionState 引用独立 WorkItem/Plan，不复制完整草稿 |
| 回复 | 已有 `AgentPresentation` 与 ChatInterface | 统一 v2 Message/Event/action 契约、可重连流 |
| 排产确认 | 已有规则 Service、版本/指纹检查 | 复用规则，统一 v2 integer revision 与 Command 幂等 |
| 旧图 | `graph.py`、写工具、checkpoint 仍有历史确认兼容 | v2 不调用；切换后删除旧执行入口与运行依赖 |
| 审计 | 部分 Run usage/工具信息缺失 | Run、ToolCall、终态审计和正式操作原子审计 |

## 2. 代码组织建议

以下是设计冻结时的目录规划，实际文件组织以仓库为准；允许在实现时按实际复杂度合并，不要求创建只转发一行的抽象。

```text
backend/app/
  routers/agent_v2.py                  # 分会话、消息、动作路由时可拆文件
  schemas/agent/                      # DTO、事件联合类型、提取与草稿契约
  models/                             # 沿现有模型风格扩展11张相关表
  services/
    agent_session_service.py          # 接受消息/命令、授权、SessionState
    agent_event_service.py            # seq与事务事件追加、安全投影
    order_intake_item_service.py      # 工作项、匹配、版本、确认
    schedule_service.py               # 复用规则与正式排产事务
    chat_attachment_service.py        # 扩展暂存、多图与GC
  agent/
    registry.py                       # Agent类型与固定图/配置版本
    context.py                        # RunContext/GraphState/上下文选择
    worker.py                         # 领取、租约、终态与watchdog
    capabilities.py                   # 类型化能力接口，无模型身份参数
    order_intake/graph.py
    scheduling/graph.py
    prompts/                          # 范围判断、提取、对话、最终解释
    skills/                           # 录单/排单固定版本任务指导
frontend/
  components/agent/                  # 公共shell、消息、事件、action
  components/agent/order-intake/     # 原图、表单、工作项列表
  components/agent/scheduling/       # 实际队列与草案工作区
```

新图继续使用仓库锁定的 LangGraph/LangChain 版本验证实现；设计不要求追随最新 SDK。当前 requirements 包含 langgraph==1.2.9，落地前以锁定环境实际 API 为准。

## 3. 分阶段交付

| 阶段 | 交付物 | 阶段退出条件 |
| --- | --- | --- |
| D0 设计冻结 | 本文档契约评审、补充替代 ADR、现有规则差异记录 | PRD/Schema/API/Event 无冲突；业务未知事项不被擅自填补 |
| D1 数据与底座 | Alembic、Session/Message/Event/Run/Command、暂存附件 | 空库与旧库迁移、幂等、并发、越权测试通过 |
| D2 Worker闭环 | 模拟模型、领取/租约/终态、202与SSE恢复 | 断浏览器、worker失联、迟到结果测试通过 |
| D3 录单纵向闭环 | 单图提取→草稿→确认；多图队列与暂放/关闭 | 同图多单独立草稿、最新草稿、成功后按钮推进、重复创建保护 |
| D4 排单纵向闭环 | 范围判断→读取→生成/替换→人工调整→执行 | 空待排、全不可排、版本/指纹过期、重复执行保护 |
| D5 前端完善与真实模型评测 | 两入口、移动端、错误状态、评测报告 | 所有P0用例通过，模型指标有证据 |
| D6 切换与清理 | 删除旧会话与附件、新流量v2、移除旧图与旧接口 | 灰度无关键错误，回滚与恢复演练完成 |

每阶段做完整的可验证纵向切片，不能到最后才补事务与鉴权。新增业务行为与对应测试在同一变更提交；提交/推送/部署按用户届时授权执行，设计已确认不等于已授权上线。

## 4. 数据迁移与旧会话

2026-09-12 产品负责人取消旧历史保留，以下规则替代原只读迁移方案。

- 发布前成组备份数据库与附件；停止 API/Worker 后升级 `d10f0a120004`，再运行同版本 API、Worker、前端。
- 迁移删除 LEGACY 会话及其消息、附件元数据、排产草案；先将附件键写入持久 GC 队列，Worker 重试直到文件删除成功。正式订单、生产任务和新版会话不受影响。
- 清除旧审计 prompt、工具参数和邮箱副本，保留非正文审计；删除旧运行时的四张 checkpoint 表。
- 移除旧首页、历史页、旧 API、旧 Graph 与旧工具权限；默认启用新版，Worker 不再依赖 Compose profile。
- 保留原始 Alembic 链和兼容列以支持已有库升级；LEGACY 仅是迁移识别值，不是可创建或读取的产品类型。
- 此次正文删除不可通过 downgrade 恢复，需要恢复时使用成组备份；新版停用不会重新启用旧协议。不得回滚到旧 Agent 应用版本。

## 5. 需求到验收追踪矩阵

| ID | 对应需求 | 核心验收场景 | 自动化层 |
| --- | --- | --- | --- |
| AC-01 | PR-01 | 两入口固定Session类型；传图片到排单返回422；历史会话不可执行 | API、前端 |
| AC-02 | PR-02/07 | Message与accepted事件文本一致；只生成一次；来源角色不能伪造 | DB、API |
| AC-03 | PR-03 | 双标签页/双worker同时提交同Session，只有一个开放Run | PostgreSQL并发 |
| AC-04 | PR-03 | 不同Session能并行；一个长Run不占全局锁 | worker集成 |
| AC-05 | PR-04 | 3图→3项，只识别第1项；第1项确认成功后不自动启动第2项 | Graph、E2E |
| AC-06 | PR-04 | 核对期追加图片不覆盖当前草稿；运行期拒绝新消息且无残留Message | API、E2E |
| AC-07 | PR-04 | 暂放再恢复保留原图/草稿；关闭项不可确认；已创建项不能“放弃”撤单 | Service |
| AC-08 | PR-05 | 提示词注入要求建客户/直接排产，工具侧拒绝，无业务写入 | Graph、安全 |
| AC-09 | PR-05 | 下单双击/超时重试/新幂等键重复确认只产生一个订单 | 事务、E2E |
| AC-10 | PR-05 | 排产多任务中一项非法，全部回滚；重试不重复任务 | 事务 |
| AC-11 | PR-06 | 模型读v3后人工保存v4，旧工具写入被拒绝，用户修改保留 | 并发、Graph |
| AC-12 | PR-06 | dirty表单遇事件/轮询不被静默覆盖，刷新恢复服务端最新稿 | 前端 |
| AC-13 | PR-05 | 无待排订单正常完成Run；有订单全不可排展示具体原因 | Graph、Service |
| AC-14 | PR-05 | 订单内容/集合、机器能力/队列变化拒绝旧草案执行 | PostgreSQL |
| AC-15 | PR-06/07 | 浏览器断流后worker继续，SSE按seq补读、去重、完整回复只出现一次 | 集成、E2E |
| AC-16 | PR-07 | worker失联标失败，迟到工具写入和finalize被fence拒绝 | 故障注入 |
| AC-17 | PR-02 | 模型格式错/超时后输入保留、partial不冒充完成、草稿可恢复 | 模型mock |
| AC-18 | PR-04 | 多图接受中一图失效，Message/绑定/工作项/Run全部回滚 | 事务 |
| AC-19 | PR-06 | 旧“下一张”按钮版本过期不能激活错误项 | API、E2E |
| AC-20 | PR-05 | 查询/讨论草案不重新生成；替换前确认，生成失败旧草案保留 | Graph、Service |
| AC-21 | PR-07 | 越权Session/消息/附件/事件/命令/草稿全部拒绝 | 安全API |
| AC-22 | PR-07 | 删除运行中会话终止写入，GC失败可重试，完成后所有正文副本不可访问 | 故障注入 |
| AC-23 | PR-05 | m可录入但不能排产；丝/c/cm/g/t换算正确；未知单位不猜测 | 规则测试 |
| AC-24 | PR-07 | 冷启动空库升级与旧库升级同达head，ORM无漂移、legacy无执行入口 | Alembic |
| AC-26 | PR-05 | 排产确认与普通页面同时新增待排订单/改变机器能力，串行化结果或明确拒绝，不漏过期校验 | PostgreSQL并发 |
| AC-25 | PR-06 | snapshot与cursor之间发生新事件不漏读；同事务事件顺序正确 | PostgreSQL、SSE |

所有上述场景均为发布门槛，不是当前已通过结果。失败并发测试必须真实使用 PostgreSQL、独立连接和事务同步点，不能仅mock锁实现。

## 6. AI 评测方案

### 6.1 数据与记录

建立经授权、脱敏的固定评测集，首期至少100张单订单截图；按清晰/模糊、手写或聊天排版、单位类型、客户/产品歧义分层。每例保存人工标注原始字段、允许匹配对象、阻塞问题和预期追问。样例不进入公共日志或外部共享链接。

排单使用至少30组固定业务快照，覆盖空待排、全不可排、混合单位、不同机器能力、合并、已排队和冲突。范围与安全至少50条输入，含跨Agent请求、未知客户维护、图片中的指令、合法短续聊和超范围混合文本。训练/调Prompt样例与最终验收集分离，避免只测熟悉案例。

每次报告记录代码 SHA、graph_version、模型 ID、Prompt/Skills版本、配置、样例版本、运行日期、成功数/失败数、时延与token缺失率。模拟模型用于协议正确性，真实模型用于提取与任务能力，二者不能互相代替。

### 6.2 初始发布指标（待实测校准，不是已有成绩）

| 指标 | 定义 | 初始门槛 |
| --- | --- | --- |
| 合法结构输出 | 经最多一次结构修复后满足Schema | ≥99%，失败必须安全提示 |
| 清晰截图关键字段准确率 | 宽幅、厚度、数量、单位按字段比对 | ≥95%；单位错误单独列出 |
| 自动实体匹配精确率 | 自动填入ID中与人工标注一致的比例 | ≥99%；同时报告覆盖率，不能以全部留空作弊 |
| 未知/歧义不自动确认 | 标注为未知的样例没有编造正式对象 | 100% |
| 范围判断合法续聊通过率 | “500kg”“就这个”等需上下文的输入 | ≥95% |
| 非法工具/正式写入拒绝 | 非授权操作最终产生实际业务副作用 | 0次 |
| 排产硬约束正确率 | 固定快照生成与确认均符合规则 | 100% |
| 解释事实一致性 | 回复数字/结论与实际工具/业务结果一致 | ≥98%；虚构创建/执行成功0次 |

阈值未达到不能通过降低校验“修复”。优先减少自动填入、增加明确追问或改善提取/匹配；产品体验变化需记录。首期不承诺模型完全无误，人工确认仍是产品主流程。

## 7. 工程验证命令与人工验证

按实现范围运行，以下是开发阶段命令清单，本次文档交付不执行数据库升级、部署或业务测试：

```bash
# backend/ 内
venv/bin/ruff check .
venv/bin/python -m pytest -q

# frontend/ 内
npm run lint
npm run build

# 仓库根目录，专用测试/验收环境
docker compose config --quiet
docker compose exec backend alembic check
python3 -m unittest discover -s deploy/production/tests -p 'test_*.py'
```

新worker镜像、Compose和迁移需在隔离环境验证启动/关闭/重启，增加worker健康指标。空库upgrade用测试数据库执行，禁止对正式业务库drop/create。当前已加入 Playwright 和 `npm run test:agent`；其业务响应为模拟结果，完整真实模型 E2E 仍需验收。代码实际状态见 [实施进度](implementation-status.md)。

人工验收必须包括：多图逐张录入、图文与剪贴板上传、当前表单修改与Agent续聊、暂放恢复、成功后下一项按钮、排单无图入口、草案编辑/过期/替换、两用户隔离、移动端、断网重连、确认超时核实。

## 8. 风险与设计处置

| 风险 | 处置 |
| --- | --- |
| 历史对话混合两类业务，无法可靠自动分型 | LEGACY只读，新会话显式开始 |
| SessionState/Event/草稿多份数据失真 | 明确权威字段、引用、事务与revision；不全量事件溯源 |
| 追加图片触发当前项覆盖 | 接受时固定目标；QUEUED_ONLY Run只确认排队 |
| 分布式worker迟到结果 | Run终态+租约令牌+短事务检查，不自动重跑整图 |
| 草稿保存成功但回复失败 | 恢复业务快照，新Run解释已有结果，不重复生成 |
| 文本事件容量增长 | 合并delta、限制输出、分页；监测容量，首期不承诺无限保留量 |
| 确认删除业务数据 | Session删除仅清理会话数据，正式订单/生产任务与必要审计保留 |
| 现有Service提前commit或允许新配方 | 组合用例调用无中间commit路径；Agent专用Schema拒绝new配方 |

## 9. 文档交付与实施前检查

本套文档需要通过：Markdown相对链接、代码块闭合、JSON示例解析、Mermaid图语法、表数量/枚举一致性、PRD到验收追踪、与Ground Truth冲突检查。真实数据库DDL、事务锁和前端恢复行为必须在实现阶段以测试证明，文档审查不能替代它们。

### 本次文档校验记录（2026-09-11）

- 5份主体文档的14个相对链接、7个JSON代码示例、Markdown代码块闭合及表格列数检查通过，0错误。
- 7张Mermaid图通过Mermaid 11解析器语法检查；检查依赖仅安装于临时目录，未修改项目依赖。
- 数据模型11张表、PR-01至PR-07需求与26项AC验收用例完成交叉检查。
- `git diff --check`通过。
- 未运行应用测试、迁移、部署或真实模型评测：本次仅创建/整理设计文档，不修改应用实现。以上校验不等于业务代码已满足设计。
