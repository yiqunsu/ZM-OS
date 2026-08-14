# OpenClaw Agent Runtime Implementation Plan

## Phase 1: FilmOS session security

- Add `ChatSession.user_id` and its user relationship/index.
- Create an Alembic migration that preserves existing sessions as unowned legacy rows.
- Pass `CurrentUser` into list/create/read/require/delete/pending service calls and enforce ownership in SQL queries.
- Add tests proving cross-user session enumeration, history access, message send, pending access, and deletion are rejected or hidden.

## Phase 2: OpenClaw-owned files

- Create `openclaw/` configuration, locked-down `filmos-web` workspace, environment example, README, and smoke test.
- Configure a Qwen OpenAI-compatible provider and enable the private Responses endpoint.
- Disable unrelated built-in tools and autonomous workspace mutation.
- Add ignore rules for OpenClaw secrets and local mutable state.

## Phase 3: Runtime integration

- Add explicit backend HTTP/SSE client dependency if the selected library is not already a direct dependency.
- Add runtime settings and production validation without logging secret values.
- Define typed runtime events and stable safe runtime exceptions.
- Wrap current LangGraph turn/resume behavior behind the runtime boundary without rewriting its tool implementation.
- Implement OpenClaw text streaming, stable per-user/per-session routing, usage extraction, timeout/disconnect handling, and protocol validation.
- Keep the existing frontend SSE contract and message/audit persistence behavior.

## Phase 4: Compose and operations

- Add the OpenClaw service, named volume, health check, network isolation, resource limits, and bounded logs to local Compose.
- Add the equivalent pinned production service and secret validation.
- Update deployment startup/health flow without making ordinary backend availability depend on OpenClaw.
- Document local preparation: Qwen key, generated Gateway token, image pull, startup, smoke check, and chat test.
- Document upgrade/backup/rollback behavior for the OpenClaw state volume.

## Phase 5: Validation

- Backend: `venv/bin/ruff check .`
- Backend: targeted Agent/runtime/session tests, then `venv/bin/python -m pytest -q`.
- Database: upgrade a test database to head and run `alembic check`.
- Frontend: `npm run lint` and `npm run build` because the browser contract must remain unchanged.
- Compose: `docker compose config --quiet` and production Compose config validation.
- Runtime smoke: OpenClaw `/readyz`, one authenticated streamed FilmOS chat, isolated second session, and simulated Gateway outage.
- Confirm no host-published OpenClaw port, no Caddy route, no database network membership, and no secrets in tracked files or logs.

## Phase 6: Recent session navigation

- Render up to six authenticated-user sessions beneath the desktop primary navigation with a subtle divider and explicit loading, empty, and retry states.
- Use `/?session=<id>` as the navigable session identity and load PostgreSQL display history through the existing authenticated Agent API.
- Add a hover/focus delete action backed by the existing ownership-checked session endpoint, with a shared confirmation dialog and explicit write-error state.
- Preserve the current per-user backend ownership boundary; role-based sharing and administrative session visibility remain a separate permissions-design task.

## Risk and rollback points

- Preserve all unrelated dirty-worktree changes; inspect overlapping files before every patch.
- Do not remove LangGraph dependencies or checkpoint initialization until a later approved task.
- Roll back runtime behavior with `AGENT_RUNTIME=langgraph`.
- Roll back the new container by stopping OpenClaw; ordinary FilmOS APIs must remain healthy.
- Do not restore PostgreSQL merely to roll back OpenClaw code or state.
