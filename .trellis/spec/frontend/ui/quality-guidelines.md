# Frontend Quality Guidelines

## Required patterns

- Read `frontend/AGENTS.md` and relevant local Next.js docs before editing framework code.
- Keep backend calls behind `lib/api.ts` and preserve JWT handling.
- Handle loading, empty, rejected, network-failure, and retry states.
- Keep fields in `snake_case` to match the backend contract.
- Update `package-lock.json` whenever dependencies change.
- Run ESLint and a production build before delivery.

## Forbidden patterns

- Direct database connections or frontend-only authoritative business rules.
- Several competing API writes for one operation that must be atomic.
- Silent catches around important reads/writes or optimistic UI without rollback.
- Disabling TypeScript/ESLint checks to make a build pass.
- Guessing Next.js behavior from model memory when local versioned documentation exists.

## Verification

From `frontend/` run:

```bash
npm run lint
npm run build
```

There is currently no formal frontend unit or end-to-end test framework. Do not invent commands; manually verify affected interactions and report the unautomated scope as required by `meta/TESTING.md`.

### Persisted chat attachment lifecycle

When changing chat attachments, verification must cover the complete lifecycle rather than only the composer state:

- selected/pasted preview before send;
- immediate ownership transfer from composer to the optimistic user message;
- server-committed event replacement of the temporary message and attachment source;
- pre-commit failure restoration versus post-commit Agent failure without composer restoration;
- App Router remount behavior after the session URL changes;
- full-refresh restoration through authenticated persisted media without exposing filenames or storage paths.

Keep transient preview fields explicitly typed as browser-only and replace them with server attachment metadata as soon as the message is committed. Do not use module globals, object URLs, or browser storage as conversation history. Until the frontend has an automated interaction framework, perform a real browser smoke test for success, refresh, and one pre-commit failure path.

Render every available sent image thumbnail as a keyboard-operable button and provide an accessible large-image dialog. The dialog must expose explicit zoom/reset/close controls, support Escape and backdrop dismissal, restore focus to the thumbnail, keep zoomed content keyboard-scrollable, and remain usable at 320px width. Missing or unauthorized media may use a non-interactive safe placeholder.

### Restorable side-panel workflows

When an assistant message claims that a side-panel form or plan was prepared, the authenticated session must persist enough structured workspace state to reconstruct that panel after an App Router remount, full refresh, or later session re-entry. Closing or completing the workflow must clear the saved workspace. Verify agent-filled values and subsequent human edits independently; message history alone is not a substitute for editable workspace state.
