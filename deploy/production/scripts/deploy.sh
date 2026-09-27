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

# A release tag must identify committed source, never an untracked local patch.
[[ -z "$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=normal)" ]] \
  || die "Commit or preserve working-tree changes before release; do not discard them."
export APP_REVISION="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
export FILMOS_IMAGE_TAG="${APP_REVISION}"

printf 'Building backend image...\n'
if ! docker image inspect "filmos-backend:${FILMOS_IMAGE_TAG}" >/dev/null 2>&1; then
  compose build backend
fi
printf 'Building frontend image...\n'
if ! docker image inspect "filmos-frontend:${FILMOS_IMAGE_TAG}" >/dev/null 2>&1; then
  compose build frontend
fi

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
if [[ "${AGENT_V2_ENABLED:-true}" == "true" ]]; then
  compose up -d agent-worker
  wait_for_service_health agent-worker 90
else
  compose stop agent-worker
fi

compose ps
compose exec -T backend alembic check
mkdir -p "${REPO_ROOT}/.data/releases"
release_dir="${REPO_ROOT}/.data/releases/$(date -u +%Y%m%dT%H%M%SZ)-${APP_REVISION}"
mkdir -p "${release_dir}"
compose exec -T backend python scripts/deployment_report.py > "${release_dir}/backend.json"
if [[ "${AGENT_V2_ENABLED:-true}" == "true" ]]; then
  compose exec -T agent-worker python scripts/deployment_report.py > "${release_dir}/worker.json"
fi
compose images --format json > "${release_dir}/images.json"
python3 "${REPO_ROOT}/deploy/check.py" --mode production --output "${release_dir}/report.json"
if [[ "${AGENT_V2_ENABLED:-true}" == "true" ]]; then
  printf 'Verifying real model with synthetic image (one paid API call)...\n'
  compose exec -T agent-worker python scripts/verify_vision.py > "${release_dir}/vision.json" \
    || die "Image acceptance failed. See ${release_dir}/vision.json; services remain running for diagnosis."
fi
printf 'Release evidence: %s\n' "${release_dir}"
printf 'Service checks completed; browser login and upload acceptance are still required.\n'

deployed_commit="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || printf unknown)"
printf 'FilmOS deployment is healthy at commit %s.\n' "${deployed_commit}"
if [[ "${WEB_BIND_IP}" == "127.0.0.1" ]]; then
  printf 'Private mode: use the documented app.filmos.test/auth.filmos.test SSH tunnel.\n'
else
  printf 'Public mode: verify https://app.zmorder.cn/healthz and the login flow.\n'
fi
