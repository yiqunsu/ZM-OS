# OpenClaw Agent Runtime Design

## 1. Architecture and trust boundaries

The browser continues to call only FilmOS FastAPI. OpenClaw is a private model/Agent runtime behind FastAPI and is never a browser-facing API.

```text
Browser -> Caddy -> Next.js / FastAPI
                         |       |
                         |       +-> PostgreSQL (FilmOS authority)
                         +----------> OpenClaw Gateway -> Qwen
```

- FastAPI owns JWT authentication, chat-session ownership, product history, audit, safe error mapping, and later business-tool execution.
- OpenClaw owns model orchestration and replaceable runtime session context.
- PostgreSQL remains the only FilmOS business-data authority.
- OpenClaw has no PostgreSQL network membership, host port, Caddy route, Docker socket, or FilmOS source mount.

## 2. Repository layout

```text
openclaw/
  README.md
  .env.example
  config/openclaw.json
  workspace/AGENTS.md
  workspace/SOUL.md
  workspace/TOOLS.md
  tests/smoke.sh
```

The directory contains FilmOS-owned configuration and prompts only. It does not vendor OpenClaw source. Compose uses a pinned official prebuilt slim image; a custom Dockerfile is deferred until a real plugin dependency requires one.

`meta/` receives only a concise durable architecture update if this runtime boundary is accepted after testing. Implementation details remain in `openclaw/README.md` and deployment documentation.

## 3. Container and network design

The `openclaw` service has:

- a pinned official slim image (prefer immutable digest for production);
- a dedicated `openclaw_state` volume mounted at `OPENCLAW_STATE_DIR`;
- the committed workspace mounted read-only;
- a readiness probe against `/readyz`;
- bounded Docker JSON logs;
- an initial 640-768 MB memory limit and no browser image;
- `no-new-privileges`, no host port, and no Docker socket.

Networks:

- `application`: Caddy, frontend, backend;
- `database` (internal): backend, PostgreSQL;
- `agent` (internal): backend, OpenClaw;
- an outbound-capable OpenClaw-only network for Qwen HTTPS traffic.

The backend reaches `http://openclaw:18789` over `agent`. OpenClaw is not attached to `database` or `application`.

## 4. Configuration and secrets

OpenClaw receives:

- the provider-neutral `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` values for model access;
- `OPENCLAW_GATEWAY_TOKEN`, generated with at least 32 random bytes;
- committed non-secret provider/model and agent configuration.

FastAPI receives:

- `AGENT_RUNTIME=openclaw`;
- `OPENCLAW_BASE_URL=http://openclaw:18789`;
- the same `OPENCLAW_GATEWAY_TOKEN`;
- `OPENCLAW_AGENT_ID=filmos-web`.

The browser receives none of these values. Local secrets live in an ignored OpenClaw environment file; production secrets live in the existing mode-0600 `.env.production`.

OpenClaw is configured with one `filmos-web` agent using Qwen. Its built-in tool profile is minimal and explicitly denies shell/process execution, filesystem mutation, browser, cron, messaging, sub-agents, and autonomous skill editing. The Responses HTTP endpoint is enabled; Control UI is neither routed nor published.

## 5. Backend runtime boundary

Introduce a small typed runtime interface under `backend/app/agent/runtime/`:

```text
runtime/base.py       request/event contracts and runtime errors
runtime/openclaw.py   private Gateway HTTP/SSE client
```

Routers continue to use a FilmOS runner/orchestrator and do not know OpenClaw response shapes. The OpenClaw adapter translates Gateway SSE into internal events; the existing runner dispatches to that adapter or its retained LangGraph path, persists FilmOS messages/audits, and emits the existing browser SSE contract.

The first OpenClaw adapter supports only:

- text input;
- streamed assistant text;
- completion and token metadata when available;
- stable session routing;
- cancellation/disconnect cleanup where supported;
- safe timeout/unavailable/protocol errors.

No FilmOS function tools are supplied in this milestone. Confirmation endpoints remain meaningful only for LangGraph-created pending actions and are not produced by OpenClaw text turns.

## 6. Session identity and product history

`ChatSession` must gain nullable `user_id` ownership through Alembic. New sessions always set `user_id=current_user.id`; all session list/read/send/delete/pending checks filter by that user.

Existing rows cannot be attributed safely. Migration leaves them unowned and application queries hide them. They are retained for manual recovery rather than deleted or assigned to an arbitrary account.

OpenClaw receives an opaque stable session identifier derived server-side from both FilmOS user id and chat session id. The raw Gateway token never reaches the client. FilmOS PostgreSQL remains the UI/history authority, so an OpenClaw restart does not remove displayed history. Runtime context loss may affect model recall but cannot affect orders or other business data.

## 7. Storage and backup boundary

OpenClaw needs no external SQL database. It creates and migrates its own SQLite state beneath `OPENCLAW_STATE_DIR`; the named volume preserves that state across container replacement.

For the first text-chat milestone, the OpenClaw volume is operational rather than business-critical because FilmOS messages remain in PostgreSQL. It is excluded from the PostgreSQL dump script. Before OpenClaw upgrades, operators should use OpenClaw's verified backup command or snapshot the stopped volume. If channels or irreplaceable OpenClaw-only memory are enabled later, its backup policy must be reassessed.

## 8. Failure behavior

- Missing runtime configuration fails Agent requests with a stable safe error.
- Gateway timeout, invalid SSE, authentication failure, and unavailability are logged with stable event names but without tokens, prompt content, or upstream response bodies.
- Agent endpoints return a safe `503`/SSE error event as appropriate.
- Backend startup and `/health` do not depend on OpenClaw readiness; non-Agent APIs remain available.
- Partial assistant text is not persisted as a completed message after a failed turn.

## 9. Migration and rollback

1. Add ownership migration and enforce it at the chat-service boundary.
2. Add runtime interface and OpenClaw client while retaining LangGraph files.
3. Add local and production OpenClaw container/configuration.
4. Test with `AGENT_RUNTIME=openclaw` using new chat sessions.
5. Roll back by switching the runtime setting to LangGraph and redeploying; no business data rollback is required.

Removal of LangGraph, PostgreSQL checkpoint tables, Phoenix-specific LangGraph instrumentation, and business-tool parity are explicitly deferred.
