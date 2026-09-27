# 0011 development 开发与语义化版本发布

状态：Accepted

日期：2026-09-27

## 背景

用户要求日常开发集中于 development，一批更新成熟后通过 main 发布，并区分 patch、minor、major。
此前 main 上直接迭代，development 落后，前端包版本不能代表线上版本，没有正式标签。

## 决策

采用两个长期分支、发布 PR、唯一 VERSION 文件和不可变版本标签。
以已部署提交 91aea31 为 v1.0.0，不改写既有部署历史。
版本在 development 准备，PR 标签验证预期版本；合并 main 自动生成 Release 并回同步。
发布与服务器部署分离；服务器按标签检出，继续使用现有备份、迁移和健康检查流程。
具体规则和操作见 [RELEASING](../RELEASING.md)。

## 后果

main 需要 PR 与必需检查，禁止 squash/rebase 破坏长期分支关系。
首个基线标签之前没有 VERSION，后续只允许这一项已知引导例外。
紧急修复如与未发布功能混杂，须另行明确方案；不提供默认绕过保护。
