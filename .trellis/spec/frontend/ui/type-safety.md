# Type Safety

TypeScript runs in strict mode. Backend JSON contracts use `snake_case`, and frontend request/response types must match them.

## Rules

- Keep component props and API return values explicitly typed.
- Put shared feature types in a focused module, such as `components/kanban/types.ts`; keep one-off local types near their use.
- Keep NextAuth augmentation in `types/next-auth.d.ts`.
- Use the generic methods in `lib/api.ts` consistently, but remember a TypeScript assertion does not validate untrusted runtime JSON.
- Avoid `any`, double assertions, non-null assertions without a proven invariant, and repeated near-duplicate entity types.
- When the API changes, update schemas, frontend types, calls, tests, and docs together.

The project does not currently use Zod or generated OpenAPI types. Do not introduce either implicitly; adopting one is a separate engineering decision.
