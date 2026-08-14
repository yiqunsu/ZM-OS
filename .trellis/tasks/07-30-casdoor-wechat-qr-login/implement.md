# Casdoor 微信扫码登录实施计划

## 1. Configuration and initialization

- [x] 为生产环境增加默认关闭的微信登录开关、AppID 和 AppSecret，并在启用时强制校验非空、非占位值。
- [x] 扩展 Casdoor runtime init generator：创建 `WeChat/Web` Provider，安全绑定到 FilmOS application，禁用 signup/自动绑定，并保留 Password 登录。
- [x] 确保禁用功能时生成结果与现有认证行为兼容，且任何输出都不打印 AppSecret。

## 2. Deployment verification and operations

- [x] 扩展 Casdoor 部署验证：启用时检查 Provider 类型、AppID、应用绑定、`canSignUp=false`、`canSignIn=true`、空 binding rule 和 WeChat signin method；不读取或输出密钥明文。
- [x] 更新生产 runbook：微信开放平台网站应用、`auth.zmorder.cn` 回调域名、邀请用户、首次密码登录绑定微信、解绑和恢复步骤。
- [x] 对已初始化 Casdoor 明确记录控制台配置步骤；验证缺少 Provider 时 fail closed，不直接修改 Casdoor 内部数据库结构。

## 3. Tests and validation

- [x] 自动化测试微信开关关闭/开启、缺失凭证、Provider JSON 和秘密不进入前端配置。
- [x] 运行 Casdoor 配置生成/验证、Shell/Python 静态检查、Compose config、后端测试、前端 lint/build。
- [ ] 真实生产环境人工验证：密码登录并绑定微信、电脑扫码登录、陌生微信拒绝、OWNER/OPERATOR、刷新、退出和微信不可用时的密码恢复。

## Rollback

- 关闭 `WECHAT_LOGIN_ENABLED`，重新生成 Casdoor 配置并按 runbook 从 application 移除微信入口。
- 保留 Provider、用户 WeChat 标识和角色数据以便诊断；不自动删除身份数据。
- FilmOS OIDC、FastAPI RBAC 和数据库 migration 不需要回滚。
