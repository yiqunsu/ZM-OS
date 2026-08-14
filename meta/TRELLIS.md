# Trellis 使用约定

状态：Normative

FilmOS 使用 [Trellis](https://github.com/mindfold-ai/Trellis) 管理 AI 编程任务、按范围注入规范和保留开发会话记忆。当前初始化版本为 `0.6.10`，采用官方根目录 `.trellis/` 和 Codex 集成。

## 目录职责

| 路径 | 职责 | 是否项目事实源 |
| --- | --- | --- |
| `meta/` | 业务 Ground Truth、跨工具工程规范、测试、可观测性和 ADR | 是 |
| `.trellis/spec/` | 面向 Agent 的 backend/frontend 分层规则和上下文索引 | 否；不得与 `meta/` 冲突 |
| `.trellis/tasks/` | 任务 PRD、设计、实现计划、上下文清单和状态 | 仅对对应任务有效 |
| `.trellis/workspace/` | 开发者会话日志与工作索引 | 否 |
| `.trellis/scripts/` | Trellis 任务和上下文脚本 | 上游生成文件 |
| `.agents/skills/` | Trellis 提供给 Codex 等 Agent 的 skills | 上游生成文件 |
| `.codex/` | Codex agents、hooks 和项目配置 | 上游生成文件及少量项目配置 |

发生冲突时，按 `meta/README.md` 的信息优先级处理。Trellis spec 应尽快修正，不能用自动更新覆盖 Ground Truth。

## 当前配置

- 开发者标识：本地 `.trellis/.developer`，该文件被忽略，不提交；
- monorepo packages：`frontend/` 与 `backend/`；
- session 自动提交：关闭。Trellis 可以更新日志和任务文件，但不会自行执行 Git commit；
- Codex dispatch：保留 Trellis 默认模式；是否实际创建任务或分派 Agent，仍需遵守当前用户授权和会话规则。

## 日常使用

查看上下文与任务：

```bash
python3 ./.trellis/scripts/get_context.py --mode packages
python3 ./.trellis/scripts/task.py list
python3 ./.trellis/scripts/task.py current
```

Trellis skills 安装在 `.agents/skills/`。在支持自动发现的 Codex 会话中，可以使用 `trellis-start`、`trellis-before-dev`、`trellis-check`、`trellis-update-spec` 和 `trellis-finish-work` 等流程。

## Codex hooks

项目已生成 `.codex/hooks.json`，但 hooks 是否执行由用户级 Codex 配置控制。需要在用户级 `~/.codex/config.toml` 的 `[features]` 下启用：

```toml
[features]
hooks = true
```

Codex 0.129 及以上版本还需要在应用中运行一次 `/hooks` 审核并批准项目 hooks。未启用 hooks 时，Trellis 文件和 skills 仍存在，但工作流状态与子 Agent 上下文不会自动注入。

不要由仓库脚本直接修改用户级 Codex 配置；这是每位开发者自己的信任决定。

## 更新与回滚

更新前先保证工作区可审查，并查看当前版本：

```bash
cat .trellis/.version
npx --yes @mindfoldhq/trellis@0.6.10 update
```

升级到新版本时，应显式替换命令中的版本号，审查 `.trellis/`、`.agents/skills/`、`.codex/` 和 `.gitattributes` 的差异，再运行 `meta/TESTING.md` 中的 Trellis 验证。不要长期使用未固定的 `@latest` 执行项目更新。

如果不再采用 Trellis，先保留需要的 task、spec 和 workspace 记录，再按官方卸载流程处理；不要直接删除未审查的项目记忆。

## 安全边界

- task、spec 和 journal 都会进入 Git 审查范围，不得写入密码、Token、Cookie、API Key 或数据库凭证；
- 不把客户敏感内容、完整 Prompt 或生产数据复制到会话日志；
- Trellis workflow 不扩大 Agent 权限，也不授权自动提交、推送、部署或其他外部写操作；
- 上游模板与 CLI 属于开发工具依赖，不进入 FilmOS 运行时或业务容器。
