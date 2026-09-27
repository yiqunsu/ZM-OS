#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command docker
require_command git
require_command python3
load_environment

"${SCRIPT_DIR}/validate-env.sh"

export APP_REVISION="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
if [[ -n "$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=normal)" ]]; then
  APP_REVISION="${APP_REVISION}-dirty"
  printf 'WARNING: deploying local changes; image revision is marked dirty.\n' >&2
fi

# Always ask Docker to build: its cache accounts for source AND build arguments.
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

has_existing_schema="$(
  compose exec -T postgres psql \
    --username "${POSTGRES_USER}" \
    --dbname "${POSTGRES_DB}" \
    --tuples-only \
    --no-align \
    --command "SELECT to_regclass('public.alembic_version') IS NOT NULL;" \
    | tr -d '[:space:]'
)"
# Quiesce API and Worker before snapshotting attachments/data or changing schema.
# A failed backup/migration deliberately leaves writers stopped for diagnosis.
printf 'Stopping application writers before backup and migration...\n'
compose stop frontend backend agent-worker

if [[ "${has_existing_schema}" == "t" ]]; then
  "${SCRIPT_DIR}/backup.sh" predeploy
else
  printf 'Fresh database detected; skipping the empty pre-deployment backup.\n'
fi

printf 'Applying Alembic migrations...\n'
compose run --rm --no-deps backend alembic upgrade head

printf 'Starting application services...\n'
compose up -d --remove-orphans backend frontend caddy
wait_for_service_health backend 180
wait_for_service_health frontend 180
wait_for_service_health caddy 60
if [[ "${AGENT_V2_ENABLED:-true}" == "true" ]]; then
  compose up -d agent-worker
  wait_for_service_health agent-worker 90
else
  compose stop agent-worker
fi

compose ps
compose exec -T backend alembic check
printf 'FilmOS deployment is healthy at revision %s.\n' "${APP_REVISION}"
printf 'No model API was called. Check login and an AI request in the browser.\n'
if [[ "${WEB_BIND_IP}" == "127.0.0.1" ]]; then
  printf 'Private mode: use the documented app.filmos.test/auth.filmos.test SSH tunnel.\n'
else
  printf 'Public mode: verify https://app.zmorder.cn/healthz and the login flow.\n'
fi
