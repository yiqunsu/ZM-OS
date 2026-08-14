# Casdoor 微信扫码登录设计

## Architecture

FilmOS 不直接调用微信接口。微信作为 Casdoor 的上游 OAuth Provider，现有 Auth.js → Casdoor OIDC → FastAPI RS256/JWKS 链路保持不变：

```text
Browser -> FilmOS /login -> Casdoor -> WeChat QR OAuth
        <- Auth.js callback <- Casdoor <- WeChat callback
        -> FastAPI /api/auth/me with Casdoor access token
```

微信 OAuth 回调域名属于 Casdoor（`auth.zmorder.cn`）；FilmOS 的 OIDC callback 仍为 `app.zmorder.cn/api/auth/callback/casdoor`。

## Configuration Contract

- `WECHAT_LOGIN_ENABLED=false`：默认关闭，避免没有有效凭证时显示坏入口。
- `WECHAT_OPEN_APP_ID`：微信开放平台网站应用 AppID。
- `WECHAT_OPEN_APP_SECRET`：微信开放平台网站应用 AppSecret，仅服务端使用。
- 启用时 Casdoor init data 新增 `OAuth / WeChat / Web` Provider。
- FilmOS application 绑定该 Provider：`canSignUp=false`、`canSignIn=true`、`canUnlink=true`、`bindingRule=[]`。
- Application 保持 `enableSignUp=false`，登录方式保留 Password 并新增 `WeChat` Tab。

运行时生成文件继续使用 `0600` 权限。AppSecret 不写入前端环境、不进入 Next.js 构建参数、不进入日志。

## Invitation and Binding Flow

1. 管理员在 Casdoor `filmos` 组织预建用户，邮箱与 FilmOS 用户一致，并只分配一个 `filmos-owner` 或 `filmos-operator` 角色。
2. 管理员向用户安全发送临时密码。
3. 用户先用账号密码登录 Casdoor，在账号设置中显式绑定微信。
4. Casdoor 把微信唯一标识保存在该用户的 WeChat 字段中。
5. 后续微信扫码解析到同一 Casdoor subject；FastAPI 继续按 subject 找到稳定的 FilmOS 本地用户 ID。

陌生微信既不能自动注册，也不能通过 Email/Phone/Name 自动绑定。密码登录作为微信故障时的恢复通道保留。

## Deployment and Compatibility

- 全新 Casdoor 数据库：初始化数据直接创建并绑定微信 Provider。
- 已初始化但未包含微信 Provider 的数据库：部署验证必须明确失败并提示管理员按 runbook 在 Casdoor 控制台添加；MVP 不通过直接 SQL 修改 Casdoor 内部表。
- 关闭功能开关时，现有 Casdoor OIDC、账号密码、本地 Credentials 和 OpenClaw 网络均不改变。
- 开启前，微信开放平台应批准网站应用并允许 `auth.zmorder.cn` 回调；真实外网扫码测试只能在域名、HTTPS 和微信配置生效后进行。

## Security and Rollback

- Provider 不允许 signup，Application 全局 signup 继续关闭。
- 绑定规则使用显式空数组，禁止默认的 Email/Phone/Name 自动关联。
- FastAPI 仍要求有效邮箱和恰好一个 FilmOS 角色；微信本身不能授予角色。
- 回滚只需关闭 `WECHAT_LOGIN_ENABLED` 并重新生成/部署 Casdoor 配置；不得删除用户、微信绑定或业务数据。
