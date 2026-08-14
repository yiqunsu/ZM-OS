# Database Guidelines

PostgreSQL is the business system of record. The backend uses SQLAlchemy 2.0 async sessions, and Alembic is the only supported schema-evolution path.

## Required patterns

- Treat one user-visible multi-row action as one transaction and one commit.
- Validate domain state before writes, while keeping database constraints as the final guard.
- Use explicit locking, sequences, constraints, or conflict retries for concurrent numbers, queue positions, and order assignment.
- Prefer `Numeric`/`Decimal` for exact quantities and timezone-aware timestamps for instants.
- Evaluate indexes for foreign keys and actual query paths; PostgreSQL does not create every needed index automatically.
- Keep historical records by archive/deactivation unless a deletion strategy is explicitly approved.

## Migrations

Run migrations from `backend/` with `alembic upgrade head`. Create schema changes through `alembic revision --autogenerate -m "..."`, then review the generated operations. Verify empty-database upgrade, existing-database upgrade, and `alembic check`.

LangGraph checkpoint tables are managed by LangGraph and intentionally excluded from Alembic autogeneration. Do not add them to FilmOS business migrations.

## Forbidden patterns

- No direct database access from `frontend/`.
- No intermediate `commit()` inside a composed business use case.
- No business correctness dependency on Redis or Phoenix.
- No model-only schema change without an Alembic migration.

## Chat attachment consistency

- `ChatAttachment` metadata and its parent user message must commit together.
- The binary file lives outside PostgreSQL. If a file write succeeds and the database transaction fails, remove the file as compensation.
- History queries must eager-load attachment metadata; API serialization must not trigger async lazy loading.
- Session deletion collects owned storage keys before the database transaction and deletes files only after the database deletion commits.
- Missing files fail as safe `404` responses; storage paths and original filenames never enter API contracts.

Normative invariants are in `meta/GROUND_TRUTH.md`; the database rules and validation matrix are in `meta/ENGINEERING_RULES.md` and `meta/TESTING.md`.
