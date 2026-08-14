# FilmOS Frontend Guidelines

These files are the Trellis context layer for frontend work. Normative product facts and cross-cutting rules remain in `meta/`; conflicts must be resolved in favor of `meta/GROUND_TRUTH.md` and the Trellis spec corrected.

Before editing `frontend/`, read `frontend/AGENTS.md` and the relevant local Next.js 16 documentation under `frontend/node_modules/next/dist/docs/`.

Read first:

- `meta/GROUND_TRUTH.md` for system and business boundaries;
- `meta/ENGINEERING_RULES.md` for frontend/API/security rules;
- `meta/TESTING.md` for required validation;
- `frontend/README.md` for current project structure.

## Guidelines index

| Guide | Scope |
| --- | --- |
| [Directory structure](directory-structure.md) | App Router, components, and shared client modules |
| [Components](component-guidelines.md) | React component, props, styling, and accessibility conventions |
| [Hooks](hook-guidelines.md) | Hooks and client data access |
| [State](state-management.md) | Local, server, session, and URL state |
| [Type safety](type-safety.md) | TypeScript contracts and runtime boundaries |
| [Quality](quality-guidelines.md) | Required checks and forbidden patterns |

Cross-layer authentication changes must also read [the backend authentication contract](../../backend/core/authentication-guidelines.md); it owns the browser Session exposure, role mapping, refresh, and logout boundary.
