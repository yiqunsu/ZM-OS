# Logging Guidelines

FilmOS emits structured JSON logs to stdout through structlog. Docker collects and rotates them.

## Runtime logs

- Request logs include timestamp, level, method, path, status, duration, and request ID.
- Use `info` for normal lifecycle and significant successful events, `warning` for degraded/recoverable conditions, and `error` for failed operations needing investigation.
- Prefer stable event names such as `phoenix_enabled` or `agent_init_failed` plus structured fields.
- Do not log passwords, JWTs, cookies, API keys, database credentials, or unnecessary customer content.

## Separate responsibilities

- structlog: runtime and request diagnostics;
- Sentry: exceptions and performance;
- Phoenix: LangChain/LangGraph traces;
- PostgreSQL audit tables: durable business/Agent audit.

None of these substitutes for another. Phoenix remains optional and must not affect business results if unavailable. Read `meta/OBSERVABILITY.md` before changing any of these systems.
