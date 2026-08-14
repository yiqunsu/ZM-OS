# Component Guidelines

FilmOS uses React function components, TypeScript, Tailwind CSS, and shared primitives under `frontend/components/ui/`.

## Rules

- Define explicit props types or interfaces; avoid `any` and unexplained assertions.
- Keep authoritative business validation on the backend. Client validation improves interaction only.
- Reuse existing UI primitives and the `cn` helper before creating parallel button, dialog, or input systems.
- Keep loading, empty, error, and retry states explicit and consistent.
- Surface failed writes; optimistic updates must restore server-authoritative state.
- Prefer composition and small feature components when one component owns unrelated concerns.

## Styling and accessibility

- Use existing Tailwind and component variants rather than isolated styling systems.
- Preserve keyboard operation, visible focus, labels, dialog semantics, and descriptive button text.
- Do not encode state only through color.

Real examples include `components/ui/button.tsx`, `components/orders/OrderForm.tsx`, and `components/kanban/TaskCard.tsx`.
