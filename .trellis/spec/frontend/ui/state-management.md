# State Management

FilmOS currently uses local React state, NextAuth session state, URL routing, and backend-fetched server state. There is no global client-state library.

## Boundaries

- Keep transient UI state local to the smallest owning component.
- Keep authentication/session state in NextAuth through `AuthSessionProvider` and `auth.ts`.
- Use route parameters and URLs for navigable identity such as order IDs.
- Treat backend data as authoritative; do not duplicate business state machines in the client.
- Derived values should be computed from source state instead of stored independently.

Promote state to a shared context or new library only when multiple distant consumers genuinely need coordinated client-owned state. Document the dependency and migration path before adding a global store.

Kanban business mutations must use one action endpoint per user intent. On success replace local machines and pending orders with the returned complete `KanbanOut`; on rejection show the backend message and refetch. Do not construct transfers, merges, splits, or reorders from multiple writes or treat optimistic state as authoritative.

Chat order confirmation sends the current `order_draft` to `/agent/chat/confirm`. The backend has already created the order when `order_created` arrives; the client only closes the panel and renders the persisted success message. Direct form creation uses `/orders/from-draft` so new formula + order remain one backend use case.
