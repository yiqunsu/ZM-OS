# Frontend Directory Structure

FilmOS uses Next.js App Router without a `src/` wrapper:

```text
frontend/
├── app/          # routes, layouts, pages, and the NextAuth route
├── components/   # feature components and reusable ui primitives
├── lib/          # shared API client and utilities
├── types/        # shared/module augmentation types
├── auth.ts       # NextAuth configuration and backend JWT creation
└── middleware.ts # route protection
```

## Placement rules

- Put route entry points in `app/<route>/page.tsx`.
- Put feature UI in `components/<feature>/`; keep reusable primitives in `components/ui/`.
- Route all backend calls through `frontend/lib/api.ts` or a future centralized API module.
- Keep shared feature types close to their feature when they are not global, as in `components/kanban/types.ts`.
- Split pages that own lists, forms, data access, and several dialogs into feature components and hooks when complexity grows.

## Real examples

- `frontend/app/kanban/page.tsx` is the route entry; `frontend/components/kanban/` owns board UI.
- `frontend/components/orders/OrderForm.tsx` is shared by new/edit routes.
- `frontend/components/chat/ChatInterface.tsx` owns the Agent SSE interaction.

Read the installed Next.js documentation before assuming framework conventions from memory.
