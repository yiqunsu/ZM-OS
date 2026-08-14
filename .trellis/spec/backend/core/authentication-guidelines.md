# Casdoor OIDC and FilmOS authorization contract

Normative role meaning is defined in `meta/GROUND_TRUTH.md`; ADR 0007 explains the architecture choice. This file is the executable implementation contract.

## Scenario: authenticated FilmOS request

### 1. Scope / Trigger

Read this spec when changing login, Auth.js sessions, JWT/JWKS handling, `users`, role checks, Caddy auth routes, Casdoor Compose/bootstrap, or code that identifies an Agent session owner.

### 2. Signatures

- Public identity projection: `GET /api/auth/me` with `Authorization: Bearer <casdoor-access-token>` returns `UserOut { id, email, role }`.
- Backend dependency: `get_current_user(...) -> CurrentUser { id: str, email: str, role: UserRole }`.
- Authorization dependency: `require_roles(*UserRole)`; master-data writes use `require_owner`.
- Database: `users.external_subject varchar(255) NULL UNIQUE`; `users.password_hash` is nullable for Casdoor-only users.
- OIDC callback: `${APP_PUBLIC_URL}/api/auth/callback/casdoor` with authorization-code, PKCE, state, and nonce checks.

### 3. Contracts

FastAPI accepts only configured RS256 access tokens with:

- registered claims `iss`, `sub`, `aud`, `iat`, `nbf`, `exp`;
- `tokenType = access-token`;
- `owner` or normalized `organization = filmos`;
- non-empty normalized `email`;
- `isForbidden != true` and `isDeleted != true`;
- `roles` containing exactly one recognized name: `filmos-owner` or `filmos-operator` (string or object with `name`).

Production env requires `AUTH_PROVIDER=casdoor`, `CASDOOR_ISSUER`, `CASDOOR_CLIENT_ID`, `CASDOOR_JWKS_URL`, and `CASDOOR_ORGANIZATION`. Auth.js additionally requires public/internal Casdoor URLs and the OIDC client secret. The browser Session may expose only the short access token plus local `id`, `email`, and `role`; refresh token and client secret stay server-side.

Identity resolution order is subject match → one-time normalized-email link → JIT local user. After linking, business/Agent ownership continues to use local `users.id`, never the OIDC subject.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Missing/malformed/expired/wrongly signed token; wrong issuer/audience/type/key | `401` with safe Chinese login-expired detail |
| JWKS unavailable and no usable cached key | `503` without provider internals |
| Wrong organization; disabled/deleted user; missing/ambiguous role; unsafe identity link | `403` |
| OPERATOR master-data write | `403` |
| Valid OWNER master-data write | Continue to business service |
| Casdoor mode password login | `404` |
| Refresh failure | Remove browser-visible access token and perform local + Casdoor logout |

### 5. Good / Base / Bad Cases

- Good: existing `Owner@Example.com` receives a valid Casdoor subject/email and is linked while retaining the same local ID and chat ownership.
- Base: a new controlled `filmos-operator` is provisioned once; concurrent first requests converge through unique constraints and winner re-read.
- Bad: trusting `roles` in React, accepting an unknown role as OPERATOR, using email on every request instead of immutable subject, or sending the Casdoor token to OpenClaw.

### 6. Tests Required

- JWT: valid token plus signature, issuer, audience, time, type, organization, status, role-object, unknown-key, cache/rotation, and unavailable-JWKS cases.
- Mapping: existing ID preservation, JIT stability, concurrent first request, email collision, and nullable-password migration.
- RBAC: authenticated reads, OPERATOR `403` on every master-data write family, OWNER success, and unchanged order/production permissions.
- Frontend/manual: redirect/callback, refresh, forced logout on refresh failure, federated logout, hidden navigation, and direct `/settings` protection.
- Infra: private/public Compose and Caddy validation, default-admin rotation check, exact callback allowlist, both database backups, and explicit restore paths.

### 7. Wrong vs Correct

Wrong:

```python
# Never authorize from an unchecked frontend/session string.
if request.headers["X-Role"] == "OWNER":
    update_master_data()
```

Correct:

```python
@router.post("", dependencies=[Depends(require_owner)])
async def create_master_data(...):
    return await service.create(...)
```

The frontend may mirror role state for navigation, but FastAPI remains the enforcement point.

## Scenario: invite-only WeChat QR login through Casdoor

### 1. Scope / Trigger

Read this scenario when adding or changing a social login Provider for Casdoor. FilmOS must never exchange a WeChat code or accept a WeChat token directly; social identities terminate at Casdoor and enter FilmOS through the existing OIDC contract above.

### 2. Signatures

- Environment: `WECHAT_LOGIN_ENABLED: true|false` (default `false`).
- Secrets when enabled: `WECHAT_OPEN_APP_ID`, `WECHAT_OPEN_APP_SECRET`.
- Casdoor Provider: `admin/provider-wechat-web`, category `OAuth`, type `WeChat`, subtype `Web`.
- Application item: `canSignUp=false`, `canSignIn=true`, `canUnlink=true`, `bindingRule=[]`.
- Signin methods: Password `All` plus WeChat `Tab`.

### 3. Contracts

WeChat login is available only in public HTTPS mode with issuer `https://auth.zmorder.cn` and an approved WeChat Open Platform website application. Accounts are invite-only: an administrator creates a Casdoor user with the existing FilmOS email and exactly one FilmOS role; the user signs in with a temporary password and explicitly links WeChat. AppSecret remains in the mode-0600 production environment/runtime init file and Casdoor database, never in frontend env, build args, browser Session, OpenClaw, logs, or Git.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Feature disabled | Password-only Casdoor behavior is preserved |
| Enabled in private HTTP mode | Deployment validation fails |
| Missing/placeholder AppID or AppSecret | Deployment/config generation fails without printing the secret |
| Unknown WeChat identity | Casdoor rejects signup; no FilmOS user or role is created |
| Existing user without explicit link | No Email/Phone/Name fallback because binding rule is explicitly empty |
| Existing initialized Casdoor lacks the application binding | Deployment verification fails and points to the runbook; scripts do not edit Casdoor tables directly |

### 5. Good / Base / Bad Cases

- Good: an invited OPERATOR binds one WeChat identity and later scans into the same Casdoor subject and local FilmOS user ID.
- Base: WeChat is disabled until ICP, HTTPS, domain approval, and credentials are ready; password login keeps working.
- Bad: enabling social signup, accepting default binding rules, deriving an email from a WeChat nickname/OpenID, or granting a default OPERATOR role.

### 6. Tests Required

- Generator: disabled output has no Provider; enabled output has exact Provider/application/signin fields and mode-0600 files.
- Rejections: invalid flag, missing credentials, private-mode enablement, and placeholders fail closed.
- Secret boundary: AppSecret name/value does not appear in frontend Auth.js, Dockerfile, production Compose, stdout, or stderr.
- Integration: pinned Casdoor image imports the Provider and persists empty `bindingRule` plus both signin methods.
- Manual public test: invite, password login, explicit bind, QR login, stranger rejection, roles, refresh/logout, and password recovery when WeChat is unavailable.

### 7. Wrong vs Correct

Wrong:

```python
# Social identity must not create a FilmOS account or role by itself.
user = User(email=f"{wechat_openid}@wechat.local", role=UserRole.OPERATOR)
```

Correct:

```json
{
  "canSignUp": false,
  "canSignIn": true,
  "canUnlink": true,
  "bindingRule": []
}
```
