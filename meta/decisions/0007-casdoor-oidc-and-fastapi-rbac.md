# ADR 0007：采用 Casdoor OIDC 与 FastAPI RBAC

- 状态：Accepted
- 日期：2026-07-29

## 背景

FilmOS 需要正式的登录、用户与角色管理能力，并要在后续接入更多 Agent 时保持统一身份边界。原有 Credentials 登录由 NextAuth 读取 FilmOS 密码并用共享 HS256 密钥签发八小时后端 Token，不适合生产账号治理、停用、角色分配和密钥隔离。

## 决策

- Casdoor 作为身份认证和粗粒度角色来源，使用 OIDC authorization-code flow、RS256 和 JWKS；
- `filmos-owner` 与 `filmos-operator` 是唯一 FilmOS 业务角色，用户必须恰好拥有其中一个；
- FastAPI 验证 access token 并执行所有业务授权，前端隐藏入口仅用于改善体验；
- FilmOS PostgreSQL 保留本地 `users.id` 作为业务归属标识。首次登录按已验证的规范化邮箱关联一次，此后只按 OIDC `sub` 识别；
- Casdoor 使用同一 PostgreSQL 服务中的独立数据库与独立登录角色，以独立容器运行；
- Auth.js 保存八小时加密会话，Casdoor access token 有效期十五分钟、refresh token 有效期二十四小时；refresh token 不进入浏览器 Session；
- OpenClaw 不接收 Casdoor Token，也不获得数据库或用户管理权限。

第一版权限为：OWNER 与 OPERATOR 均可读取业务数据、管理订单与生产任务、使用自己的 Agent 会话；只有 OWNER 可以修改基础数据；账号与角色通过 Casdoor 组织后台管理。

## 理由

这套边界把认证、业务身份和授权拆开：Casdoor 管理凭证与角色，FilmOS 保持已有业务引用稳定，FastAPI 仍是唯一业务规则执行者。短期 access token 限制角色变更和停用后的延迟，JWKS 避免前后端共享签名密钥。

## 后果与限制

- Casdoor 成为登录所需的生产服务，但已签发 Token 在短期 Casdoor 故障时仍可由 FastAPI 离线验证；
- 角色或停用变化最多延迟十五分钟生效；第一版不增加 introspection 或 webhook；
- 单机仍存在共同故障域，因此备份必须同时覆盖 FilmOS 与 Casdoor 两个数据库；
- 不提供 FilmOS 内置用户管理页，管理员必须使用 Casdoor；
- 回退到本地密码登录只保留给明确的开发模式，新建的 Casdoor 用户可能没有本地密码。

## 重新评估触发条件

- 出现多租户、更多业务角色或字段级权限需求；
- 需要即时撤销、强制 MFA、LDAP/SCIM 或企业身份源；
- FilmOS 扩展为多实例并需要服务端 Session/令牌协调；
- Casdoor 独立数据库或单机部署不再满足可用性与恢复目标。
