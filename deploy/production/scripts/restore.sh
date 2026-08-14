#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command docker
load_environment
require_disposable_restore_database "${POSTGRES_DB}"

backup_path="${1:-}"
confirmation="${2:-}"

[[ -n "${backup_path}" ]] \
  || die "Usage: restore.sh <backup.dump> --confirm-database-replacement"
[[ "${confirmation}" == "--confirm-database-replacement" ]] \
  || die "Restore replaces the database. Re-run with --confirm-database-replacement"
[[ -f "${backup_path}" && -r "${backup_path}" ]] \
  || die "Backup file is not readable: ${backup_path}"
[[ "$(basename "${backup_path}")" == filmos_*.dump ]] \
  || die "FilmOS restore requires a filmos_*.dump backup"

compose ps --status running postgres | grep -q postgres \
  || die "PostgreSQL is not running"
compose exec -T postgres pg_restore --list <"${backup_path}" >/dev/null \
  || die "Backup file failed pg_restore validation"

printf 'Stopping FilmOS application writers...\n'
compose stop caddy frontend backend || true

restore_failed() {
  printf 'Restore failed. Application services remain stopped; inspect the errors before restarting.\n' >&2
}
trap restore_failed ERR

compose exec -T postgres psql \
  --username "${POSTGRES_USER}" \
  --dbname postgres \
  --set ON_ERROR_STOP=1 \
  --command "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${POSTGRES_DB}' AND pid <> pg_backend_pid();"
compose exec -T postgres dropdb \
  --username "${POSTGRES_USER}" \
  --if-exists \
  --force \
  "${POSTGRES_DB}"
compose exec -T postgres createdb \
  --username "${POSTGRES_USER}" \
  --owner "${POSTGRES_USER}" \
  "${POSTGRES_DB}"
compose exec -T postgres pg_restore \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  <"${backup_path}"

if database_only_restore_test_requested; then
  trap - ERR
  printf 'Disposable FilmOS database restore complete; application services were intentionally not started.\n'
  exit 0
fi

compose run --rm backend alembic upgrade head
compose up -d backend frontend caddy
wait_for_service_health backend 120
wait_for_service_health frontend 120
wait_for_service_health caddy 60

trap - ERR
printf 'Restore complete and FilmOS services are healthy.\n'
