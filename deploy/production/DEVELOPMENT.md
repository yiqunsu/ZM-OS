# development 分支部署与验收

## 运行配置

- `AGENT_RUNTIME=langgraph`，设置有效的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。
- 订单图片提取使用 `LLM_VISION_MODEL` 的现有默认值。
- 默认不启动 OpenClaw；仍需回退时，显式设置 `AGENT_RUNTIME=openclaw` 并启用 `--profile openclaw`，配置旧 Gateway 和 QWEN 凭证。
- LangGraph Prompt：`backend/app/agent/prompt_templates/scheduling-v1.md`。修改后重建后端镜像。
- 本次无数据库结构变更。上线仍需按原流程执行迁移、备份并检查模型配置。

## 发布方式

先推送经过验证的 development 提交，再在服务器检出这个提交。不要覆盖服务器未提交配置。
记录 `git rev-parse HEAD`，通过现有 `scripts/deploy.sh` 构建部署。
现有脚本生成 `production` 标签，发布记录必须同时记录 Git SHA；分支名不是不可变镜像版本。
本地 development 修改不会自动同步到 GitHub 或服务器。

## 员工验收

1. 左侧要求生成排产方案，右侧出现未执行草案；实际任务数未增加。
2. 拖动订单更换机器、合并、退回或通过箭头重排。非法宽度/花纹/合并被拒绝。
3. 在其他页面改变实际生产数据，右侧五秒内提示草案过期。
4. 重新生成后核对并执行；实际队列更新，刷新会话能看到结果。
5. 另一个用户不能读取、修改、执行此会话草案。
6. 网络失败后重新加载核实状态；重复执行不新增任务。

当前支持人工调整，不支持自然语言调整或跨系统任务。投入正式生产前需要真实模型与员工交互验收。
