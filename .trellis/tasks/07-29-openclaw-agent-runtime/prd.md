# Connect FilmOS agent to OpenClaw

## Goal

Run OpenClaw as an independently configured container and connect the existing FilmOS web chat to it through FastAPI, without exposing OpenClaw credentials or its Gateway directly to the browser.

The first delivery should establish a safe, reversible runtime connection. FilmOS remains the authority for authentication, business rules, write confirmation, chat display history, and PostgreSQL data.

## Background and confirmed facts

- The current frontend posts JSON to `POST /agent/chat` and consumes the FilmOS SSE event contract (`delta`, `text_done`, confirmation, panel, and form events).
- FastAPI currently runs a LangGraph loop and persists display messages and agent audits in PostgreSQL.
- LangGraph checkpoints currently hold resumable write-tool confirmation state.
- Production uses one Docker Compose host with Caddy, Next.js, FastAPI, and PostgreSQL on a 2-core/4-GB Tencent Cloud Lighthouse instance.
- OpenClaw provides a Gateway container, authenticated HTTP APIs, SSE, sessions, client function tools, images, and files.
- OpenClaw owns embedded SQLite databases inside `OPENCLAW_STATE_DIR`; it does not require an external PostgreSQL, MySQL, or Redis service.
- OpenClaw's shared Gateway token is an operator credential and must never be delivered to the browser or exposed through Caddy.
- Existing `chat_sessions` rows have no user ownership column and the current chat service does not filter sessions by authenticated user. Safe OpenClaw session isolation therefore requires adding ownership at the FilmOS boundary rather than relying only on an OpenClaw session key.
- `meta/` should record only important long-term facts. Local OpenClaw configuration belongs in a root `openclaw/` directory; a new ADR is warranted only if the final runtime boundary is adopted as a durable architectural decision.

## Requirements

1. Add a root `openclaw/` directory containing FilmOS-owned OpenClaw configuration, workspace instructions, documentation, and smoke-test assets; do not vendor the OpenClaw source tree.
2. Run OpenClaw as a separate container using a pinned official prebuilt slim image, persistent runtime state, a health check, bounded logs, and resource limits appropriate for the current server.
3. Do not publish an OpenClaw host port, route it through Caddy, connect it to the PostgreSQL network, mount the Docker socket, or expose its Gateway token to frontend code.
4. Configure OpenClaw to use Qwen while disabling shell, filesystem mutation, browser, cron, messaging, sub-agent, and other unrelated built-in tools for the FilmOS web agent.
5. Keep the browser-facing FilmOS `/agent/*` API and SSE contract stable. FastAPI owns OpenClaw authentication and translates OpenClaw streaming events into FilmOS events.
6. Introduce a backend Agent Runtime boundary so OpenClaw can be selected without coupling routers or business tools directly to one runtime implementation.
7. Keep PostgreSQL chat messages and audits as FilmOS product records. Treat OpenClaw session state as replaceable runtime state, scoped by FilmOS user and chat session.
8. OpenClaw failure must degrade only Agent endpoints; ordinary authenticated business APIs and backend health must continue working.
9. Preserve the dirty worktree and do not overwrite concurrent frontend changes.
10. The first OpenClaw milestone provides text streaming and session isolation only. Existing FilmOS order-draft, scheduling, and write-confirmation tools do not need to be ported to OpenClaw in this milestone.
11. LangGraph removal or tool integration is deferred. The OpenClaw text-chat path must be independently testable before business-task design begins.
12. Add FilmOS user ownership to chat sessions. New sessions must belong to the authenticated user; list, history, send, and delete operations must enforce ownership. Existing unowned legacy sessions must be retained but hidden rather than guessed or exposed across users.
13. Persist OpenClaw's `OPENCLAW_STATE_DIR` in a dedicated named volume. The volume is operational Agent state, not a FilmOS business database and not a replacement for PostgreSQL history.
14. Show a compact list of the authenticated user's recent chat sessions in the desktop sidebar below the primary navigation, separated by a subtle divider. Selecting a session must restore its PostgreSQL-backed display history, and the active session must be represented in the URL.
15. Allow users to delete their own sessions from the recent-session list with explicit confirmation and visible failure feedback. Deleting the active session must return the UI to a new conversation.

## Acceptance Criteria

- [ ] OpenClaw starts independently and passes its container readiness check.
- [ ] No OpenClaw port is published to the host and Caddy has no OpenClaw route.
- [ ] An authenticated FilmOS user can send a text message through the existing chat page and receive streamed text generated through OpenClaw.
- [ ] The OpenClaw Gateway token exists only in server-side/container configuration.
- [ ] Two FilmOS chat sessions use isolated OpenClaw session keys, and one FilmOS user cannot select another user's session.
- [ ] Existing unowned legacy chat sessions are not automatically assigned to an arbitrary user and are not exposed through authenticated session APIs.
- [ ] The existing FilmOS chat history remains readable after an OpenClaw restart.
- [ ] When OpenClaw is unavailable, Agent requests return a stable safe error while order, production, login, and backend health remain available.
- [ ] Runtime selection and rollback behavior are documented and covered by backend tests using a fake OpenClaw stream.
- [ ] Production Compose validation, backend lint/tests, and relevant frontend lint/build checks pass.
- [ ] The desktop sidebar shows recent sessions for only the authenticated user; selecting one restores its history, while “new conversation” returns to an empty chat URL.
- [ ] A user can delete only their own recent session after confirmation; failed deletion leaves it visible, and deleting the active session opens a new conversation.

## Out of Scope for the first connection

- Public OpenClaw Control UI.
- WeChat, Feishu, Telegram, or other OpenClaw channels.
- Giving OpenClaw direct PostgreSQL access.
- Redis.
- Browser automation, host shell access, autonomous skill editing, cron jobs, or sub-agents.
- Removing LangGraph before OpenClaw connectivity and rollback have been verified.
- Porting the existing order-form, scheduling, or confirmed-write tools to OpenClaw.
- Full production-grade multimodal attachment storage; OpenClaw capability may be wired later through a separately designed attachment contract.
