# State Management

FilmOS currently uses local React state, NextAuth session state, URL routing, and backend-fetched server state. There is no global client-state library.

## Boundaries

- Keep transient UI state local to the smallest owning component.
- Keep authentication/session state in NextAuth through `AuthSessionProvider` and `auth.ts`.
- Use route parameters and URLs for navigable identity such as order IDs.
- Treat backend data as authoritative; do not duplicate business state machines in the client.
- Derived values should be computed from source state instead of stored independently.

Promote state to a shared context or new library only when multiple distant consumers genuinely need coordinated client-owned state. Document the dependency and migration path before adding a global store.

Kanban optimistic interaction must roll back or refetch after rejection so order/task relationships cannot remain visually inconsistent.
