# FilmOS 分支与版本发布规则

状态：Normative。2026-09-27 经产品负责人确认。

## 分支职责

- `development`：日常本地开发、测试及推送。允许直接提交，不要求每个功能建分支。
- `main`：通过发布 PR 合入的稳定代码。只接受同仓库 `development` 的发布 PR。
- 两个长期分支都保留，不自动删除。禁止强推和删除 main；不重写已发布历史。
- 发布 PR 使用 **Create a merge commit**，不使用 squash/rebase；否则长期分支共同历史会被破坏。
- 正式发布后工作流将 main 合回 development。若并发开发导致冲突，任务失败并保留现场；人工在 development 合并 origin/main、解决冲突并重新检查，禁止强推覆盖。

## 版本来源

仓库根 `VERSION` 是应用发布版本的唯一权威来源，格式为 `MAJOR.MINOR.PATCH`。
前端 package.json、package-lock.json 中的版本是派生元数据，由脚本同步，不分别手改。
后端运行诊断继续报告 Git revision，以准确区分同一发布周期内的开发提交。

首个正式版本 `v1.0.0` 固定在已上线提交 `91aea315fb8be8bcd5adb3c4908062c33a3db2fe`。
该历史提交没有 VERSION，这是唯一的引导例外；不为补文件而移动标签。
版本管理工具首批保存在 development，下一次正式发布时随业务改动合入 main。

| PR 标签 | 含义 | 从 1.1.1 升级 |
| --- | --- | --- |
| `version:patch` | 兼容的修复、小调整 | 1.1.2 |
| `version:minor` | 兼容的新功能 | 1.2.0 |
| `version:major` | 不兼容变更，需要迁移说明 | 2.0.0 |

版本只在准备发布时更新，不随每次提交递增。一个发布 PR 必须且只能有一个版本标签。
Tag 使用 `v` 前缀，必须固定到发布提交，禁止移动或复用；GitHub Release 保存更新说明。

## 日常开发

```bash
git switch development
git pull --ff-only origin development
# 修改、测试、提交，然后：
git push origin development
```

使用用户当前工作区，不清除未提交改动。临时功能分支可选，用完后合入 development。

## 准备发布

先整理这一批改动并完成对应测试，再执行（以 minor 为例）：

```bash
python3 scripts/release/version.py prepare minor
git add VERSION frontend/package.json frontend/package-lock.json
git commit -m "chore: prepare release"
git push origin development
gh pr create --base main --head development --label version:minor
```

脚本 fetch main/tags，以远端 main 的版本计算下一版本；重复执行不会反复递增。
若发布期间改选 patch/major，重新运行 prepare 对应类型并替换 PR 标签。
PR 描述应写清功能、修复、数据库迁移、env 变更和回退限制。

main 合并前要求 backend-tests、frontend-build、agent-integration、deployment-checks、release-policy 全部通过，且与最新 main 同步。
所有必需检查不使用路径过滤，避免只有文档/版本文件改动时检查永久等待。
单人项目不强制另一人审批，但必须通过 PR 和检查。

合并后 publish-release 自动：校验版本一致性 → 创建不可变 Tag → 创建 Release（自动汇总 PR）→ 合回 development。
工作流不修改 VERSION，不推版本提交到 main，不自动部署服务器。发布失败可在 main 手动重跑，已存在标签必须指向相同提交。
GitHub Actions 自带令牌发出的同步推送不会再次启动普通 push 工作流；发布提交已经通过 PR 检查。

## 服务器按版本部署

在服务器先检查工作区无未提交代码，并由用户核对服务器私有 env。保留现有数据库和身份凭证。

```bash
cd /opt/filmos
git fetch origin --tags
git checkout --detach v1.1.0  # 替换为要部署的真实版本
./deploy/production/scripts/validate-env.sh
./deploy/production/scripts/deploy.sh
```

部署脚本构建当前 checkout，不自动切换分支。记录版本标签和脚本输出的 Git revision。
下一次升级先 fetch，再 checkout 新标签；detached HEAD 下不要直接 git pull。
回退代码不能自动回退数据库。涉及不可逆迁移时，必须使用发布前数据库及附件备份，不能只切换旧镜像。

## 紧急修复

正常从 development 汇总修复后发布 patch。如果 development 已混入不能上线的功能，应先单独设计修复发布方案，不强行把所有开发内容合进 main；当前规则没有隐式绕过通道。

## 验证

```bash
python3 -m unittest discover -s scripts/release -p 'test_*.py'
python3 scripts/release/version.py check
```

测试覆盖版本进位/归零、非法版本、重复准备、元数据漂移、标签数量、版本匹配和 PR 来源。
发布自动化的首次真实合并仍需观察 Actions 成功、Tag 指向及 development 同步；v1.0.0 由初始化操作创建，不声称其经过尚未启用的自动发布流程。
