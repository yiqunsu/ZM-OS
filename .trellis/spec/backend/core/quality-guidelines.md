# Backend Quality Guidelines

## Required patterns

- Keep Python code typed and passing Ruff.
- Make the backend the only authority for business rules and permissions.
- Use Pydantic and database constraints for enforceable rules.
- Add success and rejection tests for each new business invariant.
- Test rollback for multi-entity writes and concurrency/conflict behavior where identifiers or assignments compete.
- Update API callers, migrations, tests, and normative docs in the same change when their contracts move.

## Forbidden patterns

- Business logic in routers or the frontend.
- Multi-request frontend orchestration for an operation that must be atomic.
- Broad exception swallowing, partial commits, or weakening tests to make CI pass.
- Empty abstractions such as forwarding-only repositories.
- Secrets or sensitive payloads in source, fixtures, logs, or traces.

## Verification

From `backend/` run:

```bash
venv/bin/ruff check .
venv/bin/python -m pytest -q
```

Database changes also require the migration checks in `meta/TESTING.md`. Review against `meta/GROUND_TRUTH.md` before accepting any state or relationship change.
