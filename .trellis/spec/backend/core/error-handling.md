# Error Handling

## API boundary

- Reject invalid input through Pydantic schemas where possible.
- Convert expected business conflicts into stable HTTP status codes and clear Chinese user messages.
- Do not expose database constraint text, stack traces, credentials, or internal connection details.
- Keep error response shapes stable; frontend code must not parse arbitrary prose to decide business behavior.

## Service boundary

- Services validate existence, authorization, allowed state transitions, and entity compatibility.
- Let unexpected exceptions propagate to the application error boundary and Sentry after transaction rollback.
- Do not catch broad exceptions merely to return success, continue with partial state, or hide a broken invariant.
- Optional observability initialization may degrade gracefully only when the feature is explicitly a non-business sidecar.

## Client behavior

`frontend/lib/api.ts` maps non-success responses to `ApiError` and signs out on `401`. New endpoints should provide a useful `detail` or stable structured error without leaking internals.

Test both the successful path and rejected/rollback paths according to `meta/TESTING.md`.
