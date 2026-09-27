#!/usr/bin/env bash
# Local-only launcher. Never deletes volumes or creates business/demo data.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
casdoor=false
phoenix=false
for option in "$@"; do
  case "$option" in
    --casdoor) casdoor=true ;;
    --phoenix) phoenix=true ;;
    *) printf 'Usage: %s [--casdoor] [--phoenix]\n' "$0" >&2; exit 2 ;;
  esac
done

ENV_FILE="${FILMOS_LOCAL_ENV_FILE:-${REPO_ROOT}/deploy/local/.env}"
[[ -f "$ENV_FILE" ]] || {
  printf 'ERROR: copy deploy/local/.env.example to deploy/local/.env and fill it first.\n' >&2
  exit 1
}
compose=(docker compose --project-directory "${SCRIPT_DIR}" --env-file "$ENV_FILE")
if [[ "$casdoor" == true ]] && grep -Eq '^CASDOOR_.*(replace-with|owner@example.test)' "$ENV_FILE"; then
  printf 'ERROR: fill the Casdoor section in deploy/local/.env before starting Casdoor.\n' >&2
  exit 1
fi
compose+=(-f "${SCRIPT_DIR}/docker-compose.yml")
if [[ "$casdoor" == true ]]; then compose+=(-f "${SCRIPT_DIR}/compose.local-auth.yml"); fi
if [[ "$phoenix" == true ]]; then compose+=(-f "${SCRIPT_DIR}/compose.phoenix.yml"); fi

export APP_REVISION="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
if [[ -n "$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=normal)" ]]; then
  APP_REVISION="${APP_REVISION}-dirty"
fi

# Validate before building or stopping an existing local stack. Do not print secrets.
"${compose[@]}" config --quiet
# Respect the maintenance switch from the shell or selected Compose env file.
# Filter locally: never print the resolved environment (it contains credentials).
agent_enabled="$("${compose[@]}" config --environment | sed -n 's/^AGENT_V2_ENABLED=//p')"
case "${agent_enabled:-true}" in
  true|True|TRUE|1) agent_enabled=true ;;
  false|False|FALSE|0) agent_enabled=false ;;
  *) printf 'ERROR: AGENT_V2_ENABLED must be true or false.\n' >&2; exit 1 ;;
esac
"${compose[@]}" build backend frontend
"${compose[@]}" up -d --wait postgres

if [[ "$casdoor" == true ]]; then
  "${compose[@]}" run --rm --no-deps casdoor-db-init
  "${compose[@]}" run --rm --no-deps casdoor-config
  "${compose[@]}" up -d --wait casdoor
  marker="${REPO_ROOT}/.data/local-casdoor/.initialized"
  if [[ ! -f "$marker" ]]; then
    touch "$marker"
    chmod 600 "$marker"
    "${compose[@]}" run --rm --no-deps casdoor-config
    "${compose[@]}" restart casdoor
    "${compose[@]}" up -d --wait casdoor
    printf 'Casdoor bootstrap data is now locked to create-only mode.\n'
  fi
fi

# Quiesce existing writers too; a failed migration leaves them stopped.
"${compose[@]}" stop frontend backend agent-worker
"${compose[@]}" run --rm --no-deps backend alembic upgrade head
applications=(backend frontend)
if [[ "$agent_enabled" == true ]]; then applications+=(agent-worker); fi
"${compose[@]}" up -d --wait "${applications[@]}"
"${compose[@]}" exec -T backend alembic check

if [[ "$phoenix" == true ]]; then
  # Tracing is optional: failure must not prevent core services from starting.
  if ! "${compose[@]}" up -d phoenix; then
    printf 'WARNING: core services are running, but Phoenix could not start.\n' >&2
  fi
fi
"${compose[@]}" ps
printf 'Local services are ready at revision %s. No account or demo data was created.\n' "$APP_REVISION"
