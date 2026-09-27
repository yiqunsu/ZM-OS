#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${FILMOS_LOCAL_AUTH_ENV_FILE:-${SCRIPT_DIR}/.env.local-auth}"

[[ -f "${ENV_FILE}" ]] || {
  printf 'ERROR: copy %s to %s and replace every placeholder first.\n' \
    "${SCRIPT_DIR}/.env.local-auth.example" "${ENV_FILE}" >&2
  exit 1
}
if grep -q 'replace-with\|owner@example.test' "${ENV_FILE}"; then
  printf 'ERROR: replace all local-auth placeholders before starting Casdoor.\n' >&2
  exit 1
fi

export APP_REVISION="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
if [[ -n "$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=normal)" ]]; then
  APP_REVISION="${APP_REVISION}-dirty"
fi

compose=(
  docker compose
  --env-file "${ENV_FILE}"
  -f "${REPO_ROOT}/docker-compose.yml"
  -f "${REPO_ROOT}/compose.local-auth.yml"
)

"${compose[@]}" up -d --wait postgres
"${compose[@]}" run --rm casdoor-db-init
"${compose[@]}" run --rm casdoor-config
"${compose[@]}" up -d --wait casdoor

marker="${REPO_ROOT}/.data/local-casdoor/.initialized"
if [[ ! -f "${marker}" ]]; then
  touch "${marker}"
  chmod 600 "${marker}"
  "${compose[@]}" run --rm casdoor-config
  "${compose[@]}" restart casdoor
  "${compose[@]}" up -d --wait casdoor
  printf 'Casdoor bootstrap data is now locked to create-only mode.\n'
fi

"${compose[@]}" up -d --build backend frontend agent-worker
"${compose[@]}" ps
printf 'Local Casdoor login is available at %s.\n' "$(grep '^CASDOOR_ISSUER=' "${ENV_FILE}" | cut -d= -f2-)"
