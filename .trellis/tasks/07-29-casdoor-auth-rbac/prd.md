# Adopt Casdoor authentication and RBAC

## Goal

Replace the production username/password and shared-secret JWT flow with a
cloud-ready Casdoor OIDC login, while preserving FilmOS user IDs and enforcing a
small, explicit `OWNER` / `OPERATOR` permission model in FastAPI. The result must
fit the accepted single-host Tencent Lighthouse deployment and must not weaken
the private OpenClaw boundary.

## Product requirements

### Authentication

- Production login must use Casdoor through the OIDC authorization-code flow.
- Casdoor must be reachable at `auth.zmorder.cn` after ICP approval and through
  the documented SSH-tunnel test topology before public activation.
- Public self-registration and unauthenticated dynamic client registration must
  be disabled. Accounts are created by an authorized Casdoor administrator.
- The FilmOS browser session must retain the current eight-hour maximum lifetime.
  Casdoor access tokens must be short lived and refresh tokens must never be
  returned in the browser-visible session.
- Signing out of FilmOS must also end the Casdoor login session so a shared
  workstation cannot immediately sign the previous user back in.
- Production must reject local password authentication and insecure/default
  Casdoor administrator credentials.

### Identity continuity

- PostgreSQL remains the authority for FilmOS business ownership and foreign
  keys. Every authenticated Casdoor identity must map to a local `users` row.
- Existing FilmOS users must retain their current `users.id`, orders, audit
  references, and Agent chat-session ownership.
- A local user that has never been linked may be linked once by an exact,
  normalized email match from the controlled FilmOS Casdoor organization.
  After linking, the immutable OIDC `sub` is the only identity key.
- A new allowed Casdoor user may be provisioned into FilmOS on first login.
  Duplicate subjects, email collisions, ambiguous roles, forbidden users, and
  identities from another organization must fail closed.

### Version-one permission matrix

| Capability | OWNER | OPERATOR |
| --- | --- | --- |
| Read orders, kanban, and master data | Yes | Yes |
| Create, edit, and delete orders | Yes | Yes |
| Create, move, update, complete, and delete production tasks | Yes | Yes |
| Create, edit, and delete master data | Yes | No |
| Use and delete own Agent sessions | Yes | Yes |
| Read or mutate another user's Agent sessions | No | No |
| Manage Casdoor accounts and role assignments | Casdoor organization admin only | No |

- `filmos-owner` and `filmos-operator` are the only accepted Casdoor application
  roles. A user must have exactly one of them.
- FastAPI must enforce the matrix. Frontend navigation and controls may mirror
  it for usability but are never the authorization boundary.
- Casdoor role changes take effect no later than the lifetime of the current
  short-lived access token. This first version does not require per-request
  introspection or a revocation webhook.

### Deployment and operations

- Casdoor must run as a separately resource-limited container, pinned by version
  and digest, behind the existing Caddy TLS entry point.
- Casdoor must use a separate PostgreSQL database and least-privilege database
  role in the existing PostgreSQL container. It must not share FilmOS tables or
  require Redis.
- Casdoor application data and FilmOS business data must both be included in
  local backup and documented restore procedures.
- First deployment must generate runtime initialization data from non-committed
  environment secrets, create the Casdoor database idempotently even when the
  PostgreSQL volume already exists, and rotate the built-in default admin before
  Caddy can expose Casdoor.
- The 2-core/4-GB host must retain enough memory for the OS and deployment
  commands. Service limits and sequential startup/build order must be reviewed
  as part of this change.
- Redis, Phoenix, Loki, Sentry, COS, Casdoor webhooks, and additional OpenClaw
  auth modes remain outside the initial production stack.

### OpenClaw compatibility

- Browsers must continue to call FastAPI, never OpenClaw directly.
- FastAPI must continue deriving OpenClaw session identities from the stable
  local FilmOS user ID and FilmOS session ID.
- Casdoor must not receive the OpenClaw gateway token, and OpenClaw must not
  receive a Casdoor token, PostgreSQL credential, Docker socket, or user-management
  capability.

## Acceptance criteria

- [ ] A configured Casdoor user can complete OIDC login and obtain an eight-hour
      FilmOS session; invalid, expired, wrongly issued, wrongly addressed, or
      wrongly signed tokens receive `401`.
- [ ] A user with no FilmOS role, both FilmOS roles, the wrong organization, or a
      forbidden/deleted identity cannot access FilmOS.
- [ ] An existing local owner is linked without changing the local user ID, and
      existing Agent sessions remain visible only to that owner.
- [ ] A new `filmos-operator` can be provisioned on first login and receives the
      same local user ID on later logins, including concurrent first requests.
- [ ] `OPERATOR` receives `403` for master-data writes but can perform ordinary
      order, production, and own-Agent operations; `OWNER` can perform all of
      those operations.
- [ ] The frontend redirects unauthenticated users to login, starts Casdoor login
      from one clear action, refreshes access tokens, handles refresh failure by
      signing out, hides owner-only navigation from operators, and performs
      federated logout.
- [ ] Production Compose exposes only Caddy, keeps PostgreSQL/FastAPI/Next.js/
      OpenClaw/Casdoor on private networks, and starts with no Redis or Phoenix.
- [ ] Fresh and existing production PostgreSQL volumes both receive a separate
      Casdoor database/role without changing FilmOS data.
- [ ] A deployment cannot become public while the Casdoor default admin or
      placeholder credentials remain, and public mode requires both
      `app.zmorder.cn` and `auth.zmorder.cn` configuration.
- [ ] Backup validation covers both databases, and each database has an explicit
      restore path that stops application writers before replacement.
- [ ] Backend auth/RBAC tests, the full backend suite, Ruff, frontend lint/build,
      Alembic checks, Compose validation, and manual OIDC/logout/Agent smoke tests
      pass as described in `meta/TESTING.md`.

## Out of scope

- A FilmOS-native user/role administration page or direct use of the Casdoor
  management API.
- Fine-grained Casbin permissions, multiple FilmOS organizations/tenants, social
  identity providers, LDAP/SCIM, mandatory MFA, or passwordless login.
- Immediate token revocation through introspection/webhooks; the maximum delay is
  the configured access-token lifetime.
- Direct Casdoor-to-OpenClaw or browser-to-OpenClaw authentication.
- Public activation before ICP approval and the required public footer/filing
  work are complete.

## Decisions already made for this task

- Casdoor is the identity and coarse-role source; FastAPI is the only business
  authorization enforcement point.
- The production role matrix is the version-one matrix above.
- Casdoor shares the PostgreSQL server process only, not the database or login
  role. Redis is not added.
- The initial Casdoor image target is `casbin/casdoor:3.125.0` pinned to its
  published multi-platform digest during implementation.
