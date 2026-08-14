# Casdoor 微信扫码登录

## Goal

让用户在电脑浏览器访问 FilmOS 时，可以通过微信扫描 Casdoor 登录页上的二维码完成认证，同时继续由 FastAPI 执行 FilmOS 的 OWNER/OPERATOR 权限规则。

## Confirmed Facts

- 第一版只支持电脑网页扫码，不包含公众号内 H5 和微信小程序登录。
- FilmOS 已通过 Auth.js OIDC 接入 Casdoor；微信应作为 Casdoor 上游 OAuth Provider，不直接接入 Next.js 或 FastAPI。
- 微信网站应用需要用户提供审核通过的微信开放平台 AppID、AppSecret 和获准的回调域名，秘密不得提交到仓库。
- 当前 FilmOS 本地用户要求唯一邮箱；FastAPI 只接受同时包含有效邮箱且恰好包含一个 FilmOS 角色的 Casdoor Token。
- 微信身份通常不能作为可信邮箱来源，因此不能沿用“根据微信资料自动按邮箱创建/关联业务账号”的假设。
- 用户接受邀请制：管理员预创建带邮箱和唯一角色的 Casdoor 用户，用户首次使用临时密码登录并显式绑定微信，之后使用微信扫码登录。

## Requirements

- Casdoor 登录页提供微信二维码入口，并保留管理员账号密码登录作为故障恢复入口。
- 微信 OAuth 回调只进入 Casdoor；FilmOS 继续只信任 Casdoor 签发的 RS256 Token。
- 未经明确绑定和角色授权的微信身份不得访问 FilmOS 业务 API。
- 微信 Provider 禁止注册、允许登录和显式绑定；自动绑定规则为空，防止按微信昵称、空邮箱或手机号误合并账号。
- 微信 AppSecret 仅进入服务器端环境或 Casdoor 数据库，不进入前端构建产物、日志或 Git。
- 生产配置和部署校验必须在缺少微信凭证时安全失败，或者由一个明确的功能开关保持微信入口关闭。

## Acceptance Criteria

- [ ] 电脑浏览器中的 Casdoor 登录页显示微信扫码入口，扫码授权后可返回 FilmOS。
- [ ] 已授权并分配唯一 OWNER/OPERATOR 角色的微信用户能够进入 FilmOS。
- [ ] 未绑定、未授权、禁用或角色不合法的微信用户收到明确拒绝，且不会自动获得业务权限。
- [ ] 未登录到受邀账号的陌生微信不能通过扫码创建 Casdoor 用户。
- [ ] 原 Casdoor 账号密码登录、Token 刷新、联合退出和本地开发登录继续工作。
- [ ] OpenClaw 不接收微信或 Casdoor Token，也不获得新的数据库/网络权限。

## Out of Scope

- 微信公众号内 H5 OAuth。
- 微信小程序登录。
- 手机号、短信验证码以及其他社交登录。
- 使用微信资料自动授予 FilmOS 角色。

## Notes

- Casdoor 官方支持 WeChat `Web` subtype 的 PC 扫码流程。真实扫码验收依赖用户提供审核通过的微信开放平台网站应用凭证。
