# Prepare production deployment

## Goal

Make FilmOS safely deployable to the purchased Tencent Cloud Lighthouse server with a reproducible, low-cost production configuration and an operator runbook that supports private validation before ICP approval and public launch afterward.

## Background and Confirmed Decisions

- FilmOS is a monorepo with a server-rendered Next.js frontend, FastAPI backend, PostgreSQL business database, and PostgreSQL-backed LangGraph checkpoints.
- The target is one Tencent Cloud Lighthouse instance in Shanghai: Ubuntu 24.04 LTS x86_64, 2 vCPU, 4 GB RAM, 60 GB SSD, Docker 29.6.1, Docker Compose 5.3.1, and 2 GB swap.
- PostgreSQL and all application services will run on this instance. Cost efficiency is preferred over high availability.
- The user owns `zmorder.cn`. Its ICP application has been submitted and associated with the Lighthouse instance, but approval is pending.
- Previous A records for `zmorder.cn` and `www.zmorder.cn` were deleted. FilmOS will use `app.zmorder.cn` after ICP approval; the apex domain remains available for a future landing page or redirect.
- Production will not include Redis, Phoenix, or Sentry. Existing optional code paths remain available for future use, but all three are disabled/absent from the initial production runtime.
- Redis may be added later only for a concrete queue, pub/sub, distributed lock, shared rate-limit, cache, or multi-instance coordination requirement. Future OpenClaw compatibility alone does not justify it.
- PostgreSQL will use a Docker persistent volume. A local compressed backup will run daily and retain seven days; selected backups can be manually downloaded. COS integration is deferred.
- Releases will be deployed manually from the Git repository on the server. CI/CD and automated image delivery are deferred.

## Requirements

### Deployment and Network

- Add a production deployment path separate from the existing development `docker-compose.yml` so local behavior remains unchanged.
- Run only the reverse proxy, frontend, backend, and PostgreSQL in the production service graph.
- Route the frontend and `/api` through one origin. Agent SSE responses must stream through the reverse proxy without buffering delays.
- Before ICP approval, bind the web entry point to loopback only and document SSH-tunnel validation. Neither the domain nor the public IP may expose the website.
- After ICP approval, document the exact transition to `app.zmorder.cn`: DNS A record, public 80/443 firewall rules, production URL, and automatic HTTPS.
- PostgreSQL, backend, and frontend container ports must remain private to the Compose network.

### Security and Configuration

- Keep production secrets in an untracked server-side environment file with restrictive permissions; commit only a non-secret example.
- Do not ship development passwords or fallback secrets in the production path.
- Share the required authentication secret correctly between frontend and backend and configure the NextAuth canonical URL for the active launch stage.
- Disable Phoenix and Sentry explicitly and omit Redis and Phoenix services entirely.
- Pin production container/base-image versions rather than using `latest`.

### Release and Operations

- Provide an idempotent manual deployment workflow that builds images, starts PostgreSQL, creates a pre-migration backup when applicable, runs Alembic explicitly, starts the application, and reports health.
- Add health checks, `unless-stopped` restart behavior, bounded Docker log rotation, and conservative resource settings appropriate to a 4 GB host.
- Preserve PostgreSQL data across application/container recreation.
- Provide daily local compressed backups with seven-day retention, a manual download command, and a documented restore procedure.
- Document deployment, migration, rollback, log inspection, health checks, backup, restore, and post-ICP activation.

## Acceptance Criteria

- [ ] One documented production command can build and start the intended stack on Ubuntu 24.04 with Docker Compose.
- [ ] The rendered production service list contains the reverse proxy, frontend, backend, and PostgreSQL, and contains no Redis or Phoenix service.
- [ ] Before ICP approval, web ports are bound only to loopback and FilmOS is testable through an SSH tunnel.
- [ ] After the documented launch switch, `https://app.zmorder.cn` serves the frontend and `/api` through valid HTTPS.
- [ ] Login, authenticated API requests, and Agent SSE responses work through the single production origin.
- [ ] PostgreSQL and application ports are not directly published to the public host network.
- [ ] Database data survives frontend/backend container recreation and host restart.
- [ ] Alembic migration is an explicit, failing-fast deployment step.
- [ ] Core services expose useful health status, restart automatically after failure/reboot, and have bounded JSON log files.
- [ ] A daily compressed database backup is created locally, backups older than seven days are removed, and restore/download instructions are usable.
- [ ] No production secret or generated backup is tracked by Git.
- [ ] Production starts with Phoenix and Sentry disabled and without Redis.
- [ ] The operator runbook covers initial setup, private validation, public activation, routine update, rollback, backup, restore, and troubleshooting.
- [ ] Existing backend checks, frontend lint/build, and production Compose validation pass, or any unrelated baseline failure is reported precisely.

## Out of Scope and Deferred Items

- Tencent COS or another automatic off-host backup target. Until added, complete server/disk loss can destroy both the live database and local backups.
- Redis, Phoenix, Sentry, Loki, Kubernetes, managed load balancers, CDN, multi-host clustering, horizontal scaling, and high-availability PostgreSQL.
- Automated CI/CD, container registry delivery, and zero-downtime rollout.
- Public launch before ICP approval.
- OpenClaw or another external Agent integration; the deployment leaves room for a future dedicated subdomain and service.

## Risks

- The single Lighthouse host is a single point of failure.
- Local-only backups do not protect against complete disk or account loss; the operator should manually download important backups until COS is introduced.
- Application rollback across a destructive database migration may require restoring the pre-deployment backup and can lose writes made afterward; the runbook must call this out explicitly.
- The 4 GB memory limit makes resource bounds, build sequencing, swap, and log retention important.
- The existing frontend dependency audit currently reports critical/high findings in Next.js/NextAuth and transitive packages. Because frontend work is happening concurrently, dependency upgrades are deferred to a separate frontend change but are a required gate before public activation.
- The final ICP filing number is not yet available. Displaying the approved number/link in the frontend footer is deferred until approval and is also a required public-activation gate.
