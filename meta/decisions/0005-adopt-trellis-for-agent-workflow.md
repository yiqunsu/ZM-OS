# ADR 0005：采用 Trellis 管理 Agent 开发工作流

- 状态：Accepted
- 日期：2026-07-28

## 背景

FilmOS 已使用 `AGENTS.md` 与 `meta/` 保存长期业务事实和工程规范，但任务 PRD、实现上下文、会话记忆以及针对不同编码 Agent 的自动注入仍缺少统一结构。随着 Agent 辅助开发增多，仅靠入口文档容易膨胀，也难以保留每次任务的上下文。

## 决策

采用 Trellis `0.6.10`，按官方约定在仓库根目录维护 `.trellis/`，并启用 Codex 集成：

- `.trellis/tasks/` 管理任务生命周期与上下文；
- `.trellis/spec/` 提供 backend/frontend 分层 Agent 规范；
- `.trellis/workspace/` 保存开发会话日志；
- `.agents/skills/` 和 `.codex/` 保存生成的 Agent/Codex 集成；
- `meta/` 继续作为 FilmOS 业务 Ground Truth 和跨工具工程规范的权威来源；Trellis spec 是派生的执行层；
- 关闭 Trellis session 自动提交，提交和推送继续由用户明确授权。

## 备选方案

### 只继续使用 `AGENTS.md` 与 `meta/`

文件更少，但无法提供 Trellis 的任务状态、按范围上下文清单、工作日志和多平台集成。

### 把 Trellis 数据放入 `meta/trellis/`

目录表面更集中，但 Trellis CLI 与生成脚本广泛依赖根目录 `.trellis/`。自定义路径需要非官方软链接或补丁，升级和卸载风险更高。

### 将 Trellis 源码作为子模块或直接复制

会把工具实现与项目使用配置混在一起，增加仓库体积和上游同步成本，且不是官方安装模型。

## 后果

正面影响：

- 任务需求、实现上下文和检查上下文可审查、可追踪；
- backend/frontend 规范可以按任务注入，减少无关上下文；
- Codex 等工具可以复用同一套工作流和项目记忆。

代价与风险：

- 仓库新增一批生成文件，需要定期升级和审查；
- `meta/` 与 `.trellis/spec/` 存在内容漂移风险，必须保持明确的权威层级；
- Codex hooks 需要每位开发者在用户级配置中主动信任和启用；
- task 和 journal 可能积累敏感信息，必须遵守项目安全边界。
