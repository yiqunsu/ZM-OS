# Optional local Casdoor mode

The default development stack continues to use the local Credentials login.
This overlay exists only for exercising the production-style OIDC and RBAC flow.

1. Copy `.env.local-auth.example` to `.env.local-auth`.
2. Replace every placeholder. Set `CASDOOR_OWNER_EMAIL` to the email of an
   existing local FilmOS `OWNER` account to test deterministic account linking.
3. Run `./deploy/local-auth/up.sh` from any directory.
4. Open `http://localhost:3000`; Casdoor is available only on
   `http://127.0.0.1:8001`.

The overlay creates a separate PostgreSQL role and database. Casdoor joins only
the `local_auth_application` and `local_auth_database` networks. PostgreSQL is never reachable from browser code.

The application network is not Docker-internal so the loopback-only `8001`
publication works; the database network remains internal. Login branding files
are mounted both for configuration generation and under Casdoor's web assets.

The merged frontend build keeps the default browser API base at
`http://localhost:8000/api`. To use another public API base, set
`NEXT_PUBLIC_API_URL` before running `up.sh`; the frontend image must be rebuilt
because Next.js embeds this value during `next build`.

To return to normal local Credentials mode, stop the merged stack and start the
default Compose file again:

```bash
docker compose \
  --env-file deploy/local-auth/.env.local-auth \
  -f docker-compose.yml \
  -f compose.local-auth.yml \
  down
docker compose up -d
```

The generated Casdoor files live under `.data/local-casdoor/` and are ignored by
Git. Removing that directory or the PostgreSQL volume destroys local identity
state; do not treat it as a backup.
