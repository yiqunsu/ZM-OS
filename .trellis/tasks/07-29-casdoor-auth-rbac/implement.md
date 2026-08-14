# Casdoor authentication and RBAC implementation plan

## Gate

- [x] Product owner approves `prd.md`, `design.md`, and this plan.
- [x] Run `task.py start` only after that approval.
- [x] Load `trellis-before-dev` completely before changing product code.
- [x] Re-check the dirty worktree and preserve unrelated frontend/OpenClaw work.

## 1. Baseline and contracts

- [x] Read the frontend/backend Trellis guides selected by
      `trellis-before-dev`, including the installed Next.js 16 authentication,
      proxy, environment, and data-security documentation.
- [x] Record baseline backend tests/Ruff and frontend lint/build results before
      auth edits.
- [x] Add ADR 0007 for Casdoor OIDC plus FastAPI RBAC, and update Ground Truth,
      engineering rules, testing, root/frontend/backend/deployment documentation.
- [x] Define centralized Casdoor claim and FilmOS role contracts before changing
      consumers.

## 2. Local user migration and identity projection

- [x] Add an Alembic migration for unique nullable `external_subject` and
      nullable legacy `password_hash`, with the necessary index/constraint.
- [x] Update the SQLAlchemy model and schemas without changing existing IDs.
- [x] Implement transactional subject resolution, one-time normalized-email
      linking, JIT creation, claim synchronization, and uniqueness-race recovery.
- [x] Add tests for existing-user preservation, new-user stability, concurrent
      provisioning, email collision, duplicate subject, and rollback behavior.
- [x] Verify empty-database upgrade, existing-database upgrade, metadata drift,
      and downgrade/recovery expectations.

## 3. FastAPI OIDC validation and RBAC

- [x] Add fail-fast Casdoor settings for issuer, audience/client ID, private JWKS
      URL, organization, accepted algorithms, timeouts, and auth mode.
- [x] Replace production HS256 trust with strict cached JWKS validation of
      signature, issuer, audience, time, subject, token type, account status,
      organization, and exactly one FilmOS role.
- [x] Keep any legacy password path explicitly development-only and make the
      production environment validator reject it.
- [x] Introduce reusable `require_roles` authorization and protect every
      master-data write endpoint consistently.
- [x] Keep and retest Agent session ownership checks for both roles.
- [x] Return stable Chinese `401`, `403`, and temporary identity-provider `503`
      errors without leaking token/provider details.
- [x] Add success/failure tests for token validation, JWKS rotation/cache,
      unknown/ambiguous roles, operator denial, owner access, and unavailable
      Casdoor behavior.

## 4. Auth.js OIDC frontend

- [x] Replace the production Credentials provider with a minimal custom Casdoor
      OIDC provider using exact public/internal endpoints and authorization-code
      checks supported by the installed Auth.js version.
- [x] Implement access-token expiry tracking and single refresh flow; keep refresh
      tokens and client secrets out of the browser session.
- [x] Resolve the local FilmOS projection through FastAPI after sign-in/refresh
      and expose only local ID, email, role, and short-lived access token.
- [x] Replace the password form with a Casdoor login action and safe error state.
- [x] Implement federated logout and verify that refresh failure forces logout.
- [x] Update the API client/session types and owner-only settings navigation/
      route behavior without altering unrelated business-page layouts.
- [x] Add or document manual checks for direct URL navigation, both roles,
      session expiry, refresh, logout, and network failure.

## 5. Casdoor local and production services

- [x] Add reviewed Casdoor configuration/init templates with closed signup,
      disabled DCR, RS256, `JWT-Custom` minimal claims, exact roles, and no
      committed secrets/default credentials.
- [x] Pin `casbin/casdoor:3.125.0` to the verified digest and confirm amd64 image
      compatibility before committing the Compose change.
- [x] Add a separate Casdoor database role/database and an idempotent bootstrap
      path that also works with the existing production PostgreSQL volume.
- [x] Generate mode-0600 runtime init data from environment secrets and rotate/
      verify the built-in admin before Caddy starts.
- [x] Add local Compose support that does not expose Casdoor to OpenClaw or the
      database to the browser.
- [x] Add production Casdoor health checks, bounded logs, private networks, and
      conservative CPU/memory limits; rebalance total limits for the 2c/4GB host.
- [x] Extend Caddy and private/public environment validation for the distinct app
      and auth origins and exact OIDC callback URLs.
- [x] Keep Redis, Phoenix, Sentry, Loki, and COS absent from production.

## 6. Deployment, backup, and recovery

- [x] Update sequential deployment so PostgreSQL/Casdoor initialization and
      credential verification finish before frontend/backend/Caddy exposure.
- [x] Make backup create and validate a matched FilmOS+Casdoor dump set before
      retention cleanup.
- [x] Add explicit Casdoor restore support and preserve the current fail-stopped
      behavior after restore errors.
- [x] Update the runbook for required user-supplied secrets, private SSH-tunnel
      hostnames, first login/link verification, public DNS/TLS activation, role
      management, routine logs, backup, restore, and rollback limits.
- [x] Confirm OpenClaw receives no new network, token, secret, or database access.

## 7. Verification gates

- [x] `backend/venv/bin/ruff check .`
- [x] `backend/venv/bin/python -m pytest -q`
- [x] Empty and existing PostgreSQL upgrades reach Alembic head and
      `alembic check` reports no drift.
- [x] `npm run lint` and `npm run build` in `frontend/`; report all warnings.
- [x] `docker compose config --quiet` for development and production configs.
- [x] Rebuild affected images and check PostgreSQL, Casdoor, OpenClaw, FastAPI,
      Next.js, and Caddy health within the 4GB resource envelope.
- [ ] Manually verify OIDC discovery/JWKS, existing-owner link, new operator,
      `401`/`403`, refresh, federated logout, settings protection, Agent SSE,
      session deletion, and cross-user chat isolation.
- [x] Create and validate both database backups; perform restore testing against
      disposable databases/volumes, never the user's live data.
- [x] Run `trellis-check`, update the relevant specs if stable conventions were
      learned, and present all unverified production-only steps explicitly.

## Rollback points

- After the nullable migration: previous code can still run; do not drop columns.
- After Casdoor deployment but before auth switch: stop/remove Casdoor and retain
  its database for diagnosis; FilmOS remains on legacy login.
- After auth switch: revert application/config only after confirming every
  required user still has a usable authentication path.
- Never restore a pre-change database automatically; restoration is destructive
  and requires an explicit operator command.
