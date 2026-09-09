#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command docker
require_command git
load_environment

"${SCRIPT_DIR}/validate-env.sh"

printf 'Building backend image...\n'
compose build backend
printf 'Building frontend image...\n'
compose build frontend

printf 'Starting PostgreSQL...\n'
compose up -d postgres
wait_for_service_health postgres 120

casdoor_marker="${REPO_ROOT}/.data/casdoor/.initialized"
casdoor_first_boot=false
if [[ ! -f "${casdoor_marker}" ]]; then
  casdoor_first_boot=true
fi

"${SCRIPT_DIR}/provision-casdoor.sh"
printf 'Starting Casdoor...\n'
compose up -d casdoor
wait_for_service_health casdoor 180

if [[ "${casdoor_first_boot}" == "true" ]]; then
  touch "${casdoor_marker}"
  chmod 600 "${casdoor_marker}"
  "${SCRIPT_DIR}/provision-casdoor.sh"
  compose restart casdoor
  wait_for_service_health casdoor 180
  printf 'Casdoor bootstrap data is now locked to create-only mode.\n'
fi

"${SCRIPT_DIR}/verify-casdoor.sh"

if [[ "${AGENT_RUNTIME:-langgraph}" == "openclaw" ]]; then
  printf 'Starting OpenClaw...\n'
  compose up -d openclaw
  wait_for_service_health openclaw 180
fi

has_existing_schema="$(
  compose exec -T postgres psql \
    --username "${POSTGRES_USER}" \
    --dbname "${POSTGRES_DB}" \
    --tuples-only \
    --no-align \
    --command "SELECT to_regclass('public.alembic_version') IS NOT NULL;" \
    | tr -d '[:space:]'
)"
if [[ "${has_existing_schema}" == "t" ]]; then
  "${SCRIPT_DIR}/backup.sh" predeploy
else
  printf 'Fresh database detected; skipping the empty pre-deployment backup.\n'
fi

printf 'Applying Alembic migrations...\n'
compose run --rm backend alembic upgrade head

printf 'Starting application services...\n'
compose up -d --remove-orphans backend frontend caddy
wait_for_service_health backend 180
wait_for_service_health frontend 180
wait_for_service_health caddy 60

compose ps
compose run --rm backend alembic current

deployed_commit="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || printf unknown)"
printf 'FilmOS deployment is healthy at commit %s.\n' "${deployed_commit}"
if [[ "${WEB_BIND_IP}" == "127.0.0.1" ]]; then
  printf 'Private mode: use the documented app.filmos.test/auth.filmos.test SSH tunnel.\n'
else
  printf 'Public mode: verify https://app.zmorder.cn/healthz and the login flow.\n'
fi
