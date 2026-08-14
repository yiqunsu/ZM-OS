# Production deployment implementation plan

## Ordered Checklist

1. **Production file layout**
   - Add a production Compose file without changing the current development service graph.
   - Add a pinned Caddy configuration and a non-secret production environment example.
   - Extend ignore rules for real production environment files and generated backups.

2. **Container production readiness**
   - Add a production-specific frontend image definition under `deploy/production/` so browser API configuration resolves to same-origin `/api` without modifying `frontend/` source or its existing Dockerfile.
   - Pin/adjust production base images where needed and ensure development environment files are excluded from build context.
   - Add health checks, restart policies, log rotation, private networks, persistent volumes, and conservative resource controls.
   - Ensure the production service list contains no Redis or Phoenix and leaves Sentry disabled.

3. **Reverse proxy and ICP-safe modes**
   - Route `/api/*` to FastAPI and other paths to Next.js.
   - Preserve SSE streaming behavior.
   - Support loopback-only HTTP before ICP approval and `app.zmorder.cn` HTTPS after approval using server-side environment values.

4. **Deployment and migration automation**
   - Add an idempotent deployment script with configuration validation, build, database readiness, pre-migration backup, Alembic upgrade, service startup, and health reporting.
   - Avoid embedding credentials or making destructive rollback decisions automatically.

5. **Backup and restore**
   - Add a timestamped compressed PostgreSQL backup script with seven-day retention and secure file permissions.
   - Add safe restore guidance/script behavior with explicit maintenance and target confirmation.
   - Document cron installation and manual off-server download.

6. **Operator documentation**
   - Document initial Tencent Lighthouse preparation, Git SSH access, secret generation, firewall policy, private SSH-tunnel testing, routine deployment, logs/health, backups, restore, rollback, and post-ICP activation.
   - Clearly separate commands safe before ICP approval from commands that make the site public.

7. **Verification and handoff**
   - Run repository checks, production Compose rendering, image builds, and service-list assertions.
   - Exercise the loopback deployment locally where feasible, including login/API/SSE, backup creation, and health checks.
   - Inspect published ports and generated configuration for accidental secrets or unwanted services.

## Validation Commands

Run the exact commands supported by the final file names; the expected minimum set is:

```bash
cd backend
venv/bin/ruff check .
venv/bin/python -m pytest -q

cd ../frontend
npm run lint
npm run build

cd ..
docker compose --env-file <production-env> -f <production-compose> config --quiet
docker compose --env-file <production-env> -f <production-compose> config --services
docker compose --env-file <production-env> -f <production-compose> build
docker compose --env-file <production-env> -f <production-compose> ps
```

Additional focused checks:

- Confirm rendered services exclude `redis` and `phoenix`.
- Confirm PostgreSQL/backend/frontend do not publish host ports.
- Confirm pre-ICP Caddy ports bind to loopback only.
- Call FastAPI `/health` through the proxy.
- Perform a real login and authenticated API request.
- Start an Agent response and confirm SSE arrives incrementally.
- Create a backup, inspect it with PostgreSQL restore tooling, and verify retention logic without deleting unrelated files.
- Run `git diff --check` and verify no real environment or backup file is tracked.

## Risky Files and Rollback Points

- Production frontend image definition and browser API environment handling: a build-time mistake can point clients at an unreachable/private URL; keep this work outside `frontend/` to avoid colliding with concurrent UI edits.
- Production Compose and Caddy configuration: a bind error can expose internal services or violate the pre-ICP restriction.
- Deployment/migration script: Alembic must fail fast and the script must not replace a healthy deployment after failure.
- Backup retention: deletion must target only validated FilmOS backup filenames in one explicit directory.
- Restore path: must require explicit operator action and explain post-backup write loss.

## Before `task.py start`

- [x] User decisions resolved: single host, `app.zmorder.cn`, no Redis/Phoenix/Sentry/COS, seven-day local backups, manual deployment.
- [x] ICP-pending and post-approval behavior defined.
- [x] Acceptance criteria are observable and complete.
- [x] Production design and rollback boundaries documented.
- [x] User explicitly approved the final planning summary in a subsequent message.

## Validation Results

- Production environment validation passed in both ICP-pending private mode and post-approval public mode.
- Production Compose rendered exactly `postgres`, `backend`, `frontend`, and `caddy`; internal services had no published host ports, while private Caddy bound only to `127.0.0.1:80/443`.
- Pinned backend and frontend production images built successfully without modifying `frontend/` or copying its `.env.local`.
- A fresh production PostgreSQL volume upgraded through all Alembic migrations to `c354112c761f (head)`; `alembic check` reported no drift.
- All four production services reached healthy state. Caddy configuration validated in both private HTTP and public `app.zmorder.cn` automatic-HTTPS modes.
- NextAuth login, authenticated backend API access, routing separation for NextAuth versus FastAPI, and SSE content/event delivery passed through Caddy.
- Local compressed backup creation, dump validation, seven-day retention deletion, and full destructive restore/restart were exercised successfully against the isolated test database.
- Backend Ruff passed and Pytest reported `43 passed`; one existing pytest-asyncio configuration deprecation warning remains.
- Frontend lint completed with zero errors and eight existing warnings; Next.js production build passed with the existing middleware deprecation warning.
- `npm audit --omit=dev` reported nine existing production dependency findings (2 moderate, 5 high, 2 critical), primarily with patch-level fixes available for Next.js and NextAuth. Upgrades are deferred to a separate frontend change and documented as a public-launch gate.
- A successful external model response was not exercised because no production API key was used. The SSE route and streamed error event were verified without exposing credentials.
- Live public DNS/TLS was not exercised because ICP approval is still pending; only offline public-mode configuration validation was performed.
- Temporary production containers, networks, test volumes, and test backup files were removed after verification; existing development containers were left running.
