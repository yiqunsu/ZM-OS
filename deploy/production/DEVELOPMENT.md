# development 分支部署与验收

## 运行配置

- LangGraph，设置有效的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。
- 订单图片提取使用 `LLM_VISION_MODEL` 的现有默认值。
- LangGraph Prompt：`backend/app/agent/prompt_templates/scheduling-v1.md`。修改后重建后端镜像。
- 回复卡片新增 `chat_messages.presentation` 可空 JSONB 字段（迁移 `c9d8e7f60123`）。上线先备份并执行 `alembic upgrade head`，再启动新后端；旧消息保持文本展示。

## Agent 回复展示

- 模型只输出解释文字；`schemas/agent_presentation.py` 从真实工具结果生成版本化只读卡片，不解析模型 JSON 或执行模型 HTML。
- `SchedulingAdapter` 收集卡片，runner 随助手消息持久化，并通过 SSE `text_done.presentation` 发送；历史 API 使用同一契约。
- 前端 `AgentReply.tsx` 负责文字排版和卡片展示。未知卡片版本退回文字。卡片是回复时快照，不是实时看板或执行凭证。
- 新能力可扩展契约与对应展示组件；左侧不增加业务写入入口，右侧继续统一调整与确认。

## 发布方式

先推送经过验证的 development 提交，再在服务器检出这个提交。不要覆盖服务器未提交配置。
记录 `git rev-parse HEAD`，通过现有 `scripts/deploy.sh` 构建部署。
部署脚本使用固定 `production` 标签和 Docker 构建缓存；未提交改动只警告并标记版本，不生成发布报告，不调用付费模型。
当前发布步骤和模型配置见 [生产部署](README.md)。
本地 development 修改不会自动同步到 GitHub 或服务器。

## 员工验收

1. 左侧要求生成排产方案，右侧出现未执行草案；实际任务数未增加。
2. 拖动订单更换机器、合并、退回或通过箭头重排。非法宽度/花纹/合并被拒绝。
3. 在其他页面改变实际生产数据，右侧五秒内提示草案过期。
4. 重新生成后核对并执行；实际队列更新，刷新会话能看到结果。
5. 另一个用户不能读取、修改、执行此会话草案。
6. 网络失败后重新加载核实状态；重复执行不新增任务。

当前支持人工调整，不支持自然语言调整或跨系统任务。投入正式生产前需要真实模型与员工交互验收。
