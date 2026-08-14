# FilmOS OpenClaw runtime

This directory contains FilmOS-owned OpenClaw configuration and workspace instructions. It does not vendor the OpenClaw source tree. OpenClaw runs as a private Compose service and is called only by FastAPI.

## Local preparation

OpenClaw reuses the provider-neutral `LLM_API_KEY`, `LLM_BASE_URL`, and
`LLM_MODEL` values already present in `backend/.env`. Create one additional
ignored file for the private Gateway token:

```bash
printf 'OPENCLAW_GATEWAY_TOKEN=%s\n' "$(openssl rand -hex 32)" > openclaw/.env
chmod 600 openclaw/.env
```

Do not send or commit that token or the model API key.

Start the stack:

```bash
docker compose up -d postgres openclaw backend frontend
docker compose ps
```

The OpenClaw Gateway has no host-published port. Check it through the container network:

```bash
./openclaw/tests/smoke.sh
```

Then open the existing FilmOS chat page. The first milestone supports streamed text only; it deliberately has no FilmOS order or scheduling tools.

For a temporary local rollback, restart the backend with the retained LangGraph
runtime:

```bash
AGENT_RUNTIME=langgraph docker compose up -d --force-recreate backend
```

## State and storage

OpenClaw creates its own SQLite runtime state below `OPENCLAW_STATE_DIR`, persisted in the `openclaw_state` named volume. It needs no external SQL database or Redis. FilmOS chat display history remains in PostgreSQL.

At container startup, Compose copies the repository's read-only seed config into
that state directory. This lets OpenClaw maintain its own last-known-good config
metadata without writing generated files back into the repository.

Do not copy live SQLite files for backup. Before a significant OpenClaw upgrade, use the same image and mounted volume to run OpenClaw's verified backup command, or stop the container before taking a volume snapshot.

## Security boundary

- Never expose port `18789` through Compose, Caddy, or the Lighthouse firewall.
- Never send `OPENCLAW_GATEWAY_TOKEN` to frontend code.
- Never attach OpenClaw to the PostgreSQL network or mount the Docker socket.
- Keep the workspace read-only and the built-in tool profile locked down.
- Pin and test an OpenClaw image version before changing it.
