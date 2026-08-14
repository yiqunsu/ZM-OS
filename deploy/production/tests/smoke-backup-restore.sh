#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/backup-restore.compose.yml"
PROJECT_NAME="filmos-backup-restore-test-${RANDOM}-${RANDOM}"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/filmos-backup-restore.XXXXXX")"
ENV_FILE="${TEST_ROOT}/test.env"
BACKUP_DIR="${TEST_ROOT}/backups"

cleanup() {
  COMPOSE_PROJECT_NAME="${PROJECT_NAME}" \
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" \
      down --volumes --remove-orphans >/dev/null 2>&1 || true
  find "${TEST_ROOT}" -depth -mindepth 1 -delete 2>/dev/null || true
  rmdir "${TEST_ROOT}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

umask 077
mkdir -p "${BACKUP_DIR}"
cat >"${ENV_FILE}" <<'EOF'
POSTGRES_DB=filmos_restore_test
POSTGRES_USER=filmos_test
POSTGRES_PASSWORD=filmos-test-password
CASDOOR_DB=casdoor_restore_test
CASDOOR_DB_USER=casdoor_test
CASDOOR_DB_PASSWORD=casdoor-test-password
FILMOS_BACKUP_RETENTION_DAYS=1
EOF

export COMPOSE_PROJECT_NAME="${PROJECT_NAME}"
export FILMOS_ENV_FILE="${ENV_FILE}"
export FILMOS_COMPOSE_FILE="${COMPOSE_FILE}"
export FILMOS_BACKUP_DIR="${BACKUP_DIR}"
export FILMOS_RESTORE_DATABASE_ONLY_FOR_TESTS=true

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

compose up -d --wait postgres
compose run --rm casdoor-db-init
# The provisioner must be idempotent and reconcile the configured role password.
compose run --rm casdoor-db-init

compose exec -T postgres psql \
  --username filmos_test \
  --dbname filmos_restore_test \
  --set ON_ERROR_STOP=1 \
  --command "CREATE TABLE smoke_marker (value text NOT NULL); INSERT INTO smoke_marker VALUES ('filmos-original');"
compose exec -T postgres psql \
  --username filmos_test \
  --dbname casdoor_restore_test \
  --set ON_ERROR_STOP=1 \
  --command "CREATE TABLE smoke_marker (value text NOT NULL); INSERT INTO smoke_marker VALUES ('casdoor-original');"

"${DEPLOY_DIR}/scripts/backup.sh" restore_test
manifest="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'backup_*_restore_test.sha256' -print -quit)"
filmos_dump="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'filmos_*_restore_test.dump' -print -quit)"
casdoor_dump="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'casdoor_*_restore_test.dump' -print -quit)"
[[ -n "${manifest}" && -n "${filmos_dump}" && -n "${casdoor_dump}" ]]
(cd "${BACKUP_DIR}" && sha256sum --check "$(basename "${manifest}")")

compose exec -T postgres psql \
  --username filmos_test \
  --dbname filmos_restore_test \
  --set ON_ERROR_STOP=1 \
  --command "UPDATE smoke_marker SET value = 'filmos-mutated';"
compose exec -T postgres psql \
  --username filmos_test \
  --dbname casdoor_restore_test \
  --set ON_ERROR_STOP=1 \
  --command "UPDATE smoke_marker SET value = 'casdoor-mutated';"

"${DEPLOY_DIR}/scripts/restore.sh" \
  "${filmos_dump}" \
  --confirm-database-replacement
"${DEPLOY_DIR}/scripts/restore-casdoor.sh" \
  "${casdoor_dump}" \
  --confirm-database-replacement

filmos_value="$(compose exec -T postgres psql --tuples-only --no-align \
  --username filmos_test --dbname filmos_restore_test \
  --command 'SELECT value FROM smoke_marker;')"
casdoor_value="$(compose exec -T postgres psql --tuples-only --no-align \
  --username filmos_test --dbname casdoor_restore_test \
  --command 'SELECT value FROM smoke_marker;')"
[[ "${filmos_value}" == "filmos-original" ]]
[[ "${casdoor_value}" == "casdoor-original" ]]

printf 'Backup/restore smoke test passed for both disposable databases.\n'
