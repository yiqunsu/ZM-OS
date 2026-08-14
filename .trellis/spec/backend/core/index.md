# FilmOS Backend Guidelines

These files are the Trellis context layer for backend work. Normative product facts and cross-cutting rules remain in `meta/`; if a Trellis spec conflicts with `meta/GROUND_TRUTH.md`, the Ground Truth wins and the spec must be corrected.

Read first:

- `meta/GROUND_TRUTH.md` for domain invariants and system boundaries;
- `meta/ENGINEERING_RULES.md` for service, API, database, security, and transaction rules;
- `meta/TESTING.md` for required verification;
- `meta/OBSERVABILITY.md` for logging, Sentry, Phoenix, and audit boundaries.

## Guidelines index

| Guide | Scope |
| --- | --- |
| [Directory structure](directory-structure.md) | FastAPI module placement and layer ownership |
| [Database](database-guidelines.md) | SQLAlchemy, transactions, constraints, and Alembic |
| [Error handling](error-handling.md) | Stable business errors and HTTP responses |
| [Authentication](authentication-guidelines.md) | Casdoor JWT, local identity projection, RBAC, and deployment contracts |
| [Logging](logging-guidelines.md) | structlog, request logs, audit, Sentry, and Phoenix |
| [Quality](quality-guidelines.md) | Required patterns, tests, and review checks |
| [Chat attachments](chat-attachment-guidelines.md) | Persisted image metadata, SSE commit lifecycle, authorization, failure recovery, and deployment storage |
