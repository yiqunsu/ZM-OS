# Hook Guidelines

The current frontend uses React hooks directly and has no React Query/SWR or formal custom-hook layer.

## Rules

- Name custom hooks with `use*` and extract them only when stateful behavior is reused or a component has become difficult to reason about.
- Keep backend access centralized through `lib/api.ts`; a hook must not create a second auth, error, or fetch convention.
- Declare effect dependencies accurately and clean up subscriptions, timers, abort controllers, and streams.
- Do not use effects to duplicate state that can be derived during render.
- Treat SSE lifecycle and cancellation as explicit resource management.
- After a mutation, reconcile with the authoritative backend response or reload the affected server state.

`components/chat/ChatInterface.tsx` is the current SSE integration reference. New data libraries require an explicit dependency decision and lockfile update.
