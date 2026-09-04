# 智能录单与规则排产实现计划

## 1. Backend contracts and storage

- [x] 扩展聊天请求图片契约、配置和安全限制。
- [x] 新增 SchedulePlan model/schema/migration。
- [x] 新增结构化订单提取服务和测试。
- [x] 新增确定性排产生成、过期检测和原子执行服务。

## 2. Agent integration

- [x] 在 OpenClaw runner 前增加录单/排产业务路由。
- [x] 新增运行时无关 pending actions；确认订单下发和排产执行。
- [x] 保持普通 OpenClaw 文本流与 LangGraph 回滚路径。

## 3. Frontend

- [x] 输入框支持 JPG/PNG 选择、预览和移除。
- [x] 输入框支持从剪贴板粘贴 JPG/PNG，并保留同次粘贴的普通文字。
- [x] 图片以真实缩略图附件卡片预览，支持右上角移除并安全释放本地预览地址。
- [x] 图片发送后在用户消息中继续显示缩略图，刷新和重新进入会话时从受保护的持久附件恢复。
- [x] 已发送缩略图支持可访问的大图灯箱、50%–300% 缩放、重置和多种关闭方式。
- [x] 会话持久化当前工作区和订单草稿，刷新/重进恢复右侧表单，关闭或下发后清理。
- [x] 消费录单与排产 SSE 事件。
- [x] 增加右侧排产方案展示。
- [x] 确认卡片处理提交表单与执行排产后的 UI 收尾。

## 4. Validation

- [x] 修正前端镜像的构建期 API base，并覆盖默认、Local Auth、生产与自定义覆盖回归测试。
- [x] `backend/venv/bin/ruff check .`
- [x] 相关后端测试后运行 `backend/venv/bin/python -m pytest -q`
- [x] `frontend/npm run lint`
- [x] `frontend/npm run build`
- [x] `docker compose config --quiet`
- [ ] 人工验证文字录单、文件选择/剪贴板图片录单、聊天确认下发和规则排产；看板原子操作及手机非拖拽入口已完成浏览器验证。

## 5. Attachment lifecycle refactor

- [x] 新增 `ChatAttachment` model/schema/migration，历史查询预加载附件并按会话归属授权读取。
- [x] 新增本地持久文件存储服务与配置；文件写入失败/数据库提交失败时不留下半完成消息或孤儿文件。
- [x] 在用户消息持久化后立即发送 `user_message_committed` SSE 事件，事件只包含服务端 ID 和附件元数据。
- [x] 前端删除模块级图片缓存，以服务端附件为历史权威；增加同源认证媒体代理。
- [x] 发送时立即把附件从 composer 移交给乐观消息；仅在服务端确认前失败时恢复 composer。
- [x] 会话删除同步清理附件文件；附件卷纳入本地/生产 Compose 和生产备份说明。
- [x] 增加附件持久化、越权读取、删除清理、识别失败仍保留附件和刷新恢复测试。
- [x] 运行完整后端、migration、前端 lint/build、Compose 和真实浏览器刷新/失败路径验证。

## 6. Production mutation safety refactor

- [x] 抽取人工看板与智能排产共用的机器/订单兼容规则。
- [x] 新增订单移动、任务移动和同机重排的动作级原子后端接口。
- [x] 新任务使用 `WAITING`，限制合法状态迁移并保证每台机器最多一个生产中任务。
- [x] 禁止通用任务更新接口绕过原子动作和兼容校验。
- [x] 看板前端改用原子接口，成功后采用服务端快照，失败后恢复权威状态并展示错误。
- [x] 增加机器不匹配、订单占用、非法合并、失败回滚、过期重排和状态冲突测试。

## 7. Atomic order submission and scheduling score

- [x] 聊天确认携带当前草稿，后端一次提交配方、订单、成功消息、pending 和工作区状态。
- [x] 右侧人工下发复用 `/orders/from-draft`，失败不留下孤立配方。
- [x] 排产负载按 kg 折算，候选任务显示幅宽利用率和任务重量。
- [x] 排产草案覆盖待排订单集合、启用机器集合、机器能力和未完成队列指纹。
- [x] 手机待排订单提供不依赖拖拽的机器选择入口。
- [x] 移除构建期 Google 字体依赖并清零前端 lint warning。

## Rollback

- 保留 LangGraph 代码与 `AGENT_RUNTIME` 回退开关。
- 新表未被旧运行时引用；代码回滚时可保留空表。
- 排产确认失败必须回滚整个事务，不能依赖清理脚本恢复。
