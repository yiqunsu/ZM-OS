# Production deployment design

## Architecture and Boundaries

The production stack remains a single-host Docker Compose deployment:

```text
Internet (only after ICP approval)
              |
         80 / 443
              v
        Caddy reverse proxy
          |             |
          | /api/*      | everything else
          v             v
     FastAPI :8000   Next.js :3000
          |             |
          +------ internal Compose network
                         |
                         v
                   PostgreSQL :5432
                         |
                   named data volume
```

Only Caddy publishes host ports. PostgreSQL, FastAPI, and Next.js are reachable only through the private Compose network. The development Compose file is not reused as production configuration because it currently publishes internal ports and includes Redis and Phoenix.

## Public and Pre-Launch Modes

The same production topology supports two launch stages through server-side environment values:

- **ICP pending:** Caddy uses an HTTP-only site address and host ports bind to `127.0.0.1`. The operator reaches it with an SSH tunnel. DNS remains absent and public 80/443 remain closed.
- **ICP approved:** set the canonical site to `app.zmorder.cn`, change the web bind to public, add the `app` A record, and open 80/443. Caddy obtains and renews the TLS certificate automatically.

The frontend uses same-origin `/api`, so switching stages does not change browser API routing. NextAuth's canonical URL is a runtime value and is changed from the private test URL to `https://app.zmorder.cn` during activation.

## Reverse Proxy Contracts

- NextAuth's own `/api/auth/*` session/callback endpoints route to `frontend:3000`; the backend login remains an internal server-side call.
- Other `/api/*` routes go to `backend:8000` without changing the path.
- All other paths route to `frontend:3000`.
- SSE routes disable proxy response buffering or use immediate flushing so Agent tokens arrive incrementally.
- Forwarded host/protocol headers are preserved for authentication callbacks and request logging.
- Compression may be enabled for normal responses but must not accumulate an SSE response before flushing.

## Production Configuration and Secrets

A committed example lists required variable names only. The real environment file lives on the server, is ignored by Git, and is readable only by the deployment user. It contains strong PostgreSQL and authentication secrets plus optional model credentials.

Important configuration contracts:

- The backend and frontend share the backend-verifiable `AUTH_SECRET` expected by the existing JWT flow.
- The frontend reaches FastAPI internally through `http://backend:8000` for credential login.
- Browser API calls use `/api` on the current origin.
- `PHOENIX_ENABLED=false`; no Phoenix endpoint or container is present.
- Sentry DSNs are empty/unset.
- No `REDIS_URL` is required by the production service graph.
- Development `.env` files are not copied into production images or used as production secrets.

## Lifecycle and Deployment Flow

The manual deployment script/runbook follows this order:

1. Validate required environment variables and render Compose configuration.
2. Build the application images, sequencing work to avoid exhausting 4 GB RAM.
3. Start PostgreSQL and wait for its health check.
4. If an existing database is present, create a timestamped pre-deployment backup.
5. Run `alembic upgrade head` as an explicit one-shot command; stop on failure.
6. Start/recreate backend, frontend, and Caddy.
7. Wait for health checks and print service status plus operator verification commands.

Routine updates use `git pull --ff-only` followed by the same deployment command. The currently deployed commit is recorded in the deployment output/runbook for rollback.

## Persistence, Backup, and Restore

- PostgreSQL stores live data in a named Docker volume.
- A host-side backup directory stores timestamped compressed PostgreSQL dumps with restrictive permissions.
- A daily cron entry invokes the repository backup script and removes backups older than seven days only after a new dump succeeds.
- The runbook provides `scp`/equivalent instructions for downloading selected dumps.
- Restore is an explicit maintenance operation: stop application writers, verify/select a dump, recreate or clean the target database as documented, restore, run migration/current checks, and restart the stack.
- A pre-migration backup is part of deployment, but rollback does not automatically restore it because that could discard later writes.

## Health, Logs, and Resource Use

- PostgreSQL health uses `pg_isready`.
- FastAPI health uses the existing `/health` endpoint.
- Next.js health probes a local HTTP route using tooling already present in the runtime image.
- Containers use `restart: unless-stopped`.
- Docker's JSON log driver uses bounded file size/count per service. Existing structlog JSON stdout remains the backend log source; Loki is not added.
- Compose resource limits/reservations are conservative and leave headroom for Docker, the OS, and builds. PostgreSQL is tuned only where evidence supports it; no premature multi-worker scaling is added.

## Compatibility and Migration

- Local development keeps the current Compose workflow and optional Phoenix behavior.
- No business schema change is planned; production still verifies and applies the existing Alembic chain.
- The Next.js image remains standalone/server-rendered because NextAuth requires a server runtime.
- The design does not introduce a Redis contract. A future Agent/OpenClaw service can be added behind a separate subdomain and internal service boundary without changing the initial deployment.

## Rollback and Failure Handling

- If build or migration fails, the current running containers are left intact whenever possible and the deploy command exits non-zero.
- Application rollback checks out the prior known-good commit and rebuilds/recreates application services.
- Database rollback is not assumed to equal Alembic downgrade. For incompatible migrations, the operator must explicitly choose between a forward fix and restoring the pre-deploy dump, acknowledging possible data loss.
- Caddy activation is reversible by removing/pausing the `app` DNS record, closing public 80/443, and returning the bind address to loopback.
