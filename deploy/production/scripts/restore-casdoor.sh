#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command docker
load_environment
require_disposable_restore_database "${CASDOOR_DB}"

backup_path="${1:-}"
confirmation="${2:-}"

[[ -n "${backup_path}" ]] \
  || die "Usage: restore-casdoor.sh <casdoor-backup.dump> --confirm-database-replacement"
[[ "${confirmation}" == "--confirm-database-replacement" ]] \
  || die "Restore replaces the Casdoor database. Re-run with --confirm-database-replacement"
[[ -f "${backup_path}" && -r "${backup_path}" ]] \
  || die "Backup file is not readable: ${backup_path}"
[[ "$(basename "${backup_path}")" == casdoor_*.dump ]] \
  || die "Casdoor restore requires a casdoor_*.dump backup"

compose ps --status running postgres | grep -q postgres \
  || die "PostgreSQL is not running"
compose exec -T postgres pg_restore --list <"${backup_path}" >/dev/null \
  || die "Backup file failed pg_restore validation"

printf 'Stopping authentication and FilmOS application writers...\n'
compose stop caddy frontend backend casdoor || true

restore_failed() {
  printf 'Casdoor restore failed. Application services remain stopped; inspect the errors before restarting.\n' >&2
}
trap restore_failed ERR

compose exec -T postgres psql \
  --username "${POSTGRES_USER}" \
  --dbname postgres \
  --set ON_ERROR_STOP=1 \
  --command "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${CASDOOR_DB}' AND pid <> pg_backend_pid();"
compose exec -T postgres dropdb \
  --username "${POSTGRES_USER}" \
  --if-exists \
  --force \
  "${CASDOOR_DB}"
compose exec -T postgres createdb \
  --username "${POSTGRES_USER}" \
  --owner "${CASDOOR_DB_USER}" \
  "${CASDOOR_DB}"
compose exec -T postgres pg_restore \
  --username "${POSTGRES_USER}" \
  --dbname "${CASDOOR_DB}" \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  <"${backup_path}"
compose exec -T postgres psql \
  --username "${POSTGRES_USER}" \
  --dbname postgres \
  --set ON_ERROR_STOP=1 \
  --command "ALTER DATABASE ${CASDOOR_DB} OWNER TO ${CASDOOR_DB_USER};"

if database_only_restore_test_requested; then
  trap - ERR
  printf 'Disposable Casdoor database restore complete; application services were intentionally not started.\n'
  exit 0
fi

compose up -d casdoor
wait_for_service_health casdoor 180
compose up -d backend frontend caddy
wait_for_service_health backend 180
wait_for_service_health frontend 180
wait_for_service_health caddy 60

trap - ERR
printf 'Casdoor restore complete and FilmOS services are healthy.\n'
