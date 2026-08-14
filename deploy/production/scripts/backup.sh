#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command docker
require_command sha256sum
require_command awk
require_command tar
load_environment

backup_reason="${1:-manual}"
[[ "${backup_reason}" =~ ^[a-z0-9_-]+$ ]] \
  || die "Backup reason may contain only lowercase letters, numbers, underscores, and hyphens"

backup_directory="${FILMOS_BACKUP_DIR:-${REPO_ROOT}/.data/backups}"
retention_days="${FILMOS_BACKUP_RETENTION_DAYS:-7}"
[[ "${retention_days}" =~ ^[1-9][0-9]*$ ]] || die "Backup retention must be a positive number of days"

umask 077
mkdir -p "${backup_directory}"
chmod 700 "${backup_directory}"

lock_directory="${backup_directory}/.backup.lock"
mkdir "${lock_directory}" 2>/dev/null \
  || die "Another FilmOS backup is already running (or a stale lock exists at ${lock_directory})"

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
filmos_final="${backup_directory}/filmos_${timestamp}_${backup_reason}.dump"
casdoor_final="${backup_directory}/casdoor_${timestamp}_${backup_reason}.dump"
attachments_final="${backup_directory}/chat_attachments_${timestamp}_${backup_reason}.tar.gz"
manifest_final="${backup_directory}/backup_${timestamp}_${backup_reason}.sha256"
filmos_temporary="$(mktemp "${backup_directory}/.filmos_${timestamp}.XXXXXX")"
casdoor_temporary="$(mktemp "${backup_directory}/.casdoor_${timestamp}.XXXXXX")"
attachments_temporary="$(mktemp "${backup_directory}/.chat_attachments_${timestamp}.XXXXXX")"
manifest_temporary="$(mktemp "${backup_directory}/.manifest_${timestamp}.XXXXXX")"

cleanup() {
  rm -f -- \
    "${filmos_temporary}" \
    "${casdoor_temporary}" \
    "${attachments_temporary}" \
    "${manifest_temporary}"
  rmdir -- "${lock_directory}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

compose ps --status running postgres | grep -q postgres \
  || die "PostgreSQL is not running"

dump_database() {
  local database="$1"
  local destination="$2"

  compose exec -T postgres \
    pg_dump \
      --username "${POSTGRES_USER}" \
      --dbname "${database}" \
      --format custom \
      --compress 6 \
      --no-owner \
      --no-privileges \
    >"${destination}"

  [[ -s "${destination}" ]] || die "Backup output is empty for database: ${database}"
  compose exec -T postgres pg_restore --list <"${destination}" >/dev/null
}

printf 'Creating matched PostgreSQL backup set: %s\n' "${timestamp}"
dump_database "${POSTGRES_DB}" "${filmos_temporary}"
dump_database "${CASDOOR_DB}" "${casdoor_temporary}"

if ! database_only_restore_test_requested; then
  printf 'Creating chat attachment archive from the private volume...\n'
  compose run --rm --no-deps -T backend python -c \
    'from pathlib import Path; import sys, tarfile; root = Path("/app/data/chat-attachments"); root.mkdir(parents=True, exist_ok=True); archive = tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz"); archive.add(root, arcname="chat-attachments"); archive.close()' \
    >"${attachments_temporary}"
  [[ -s "${attachments_temporary}" ]] || die "Chat attachment backup output is empty"
  tar -tzf "${attachments_temporary}" >/dev/null \
    || die "Chat attachment backup failed archive validation"
fi

chmod 600 "${filmos_temporary}" "${casdoor_temporary}" "${attachments_temporary}"
filmos_hash="$(sha256sum "${filmos_temporary}" | awk '{print $1}')"
casdoor_hash="$(sha256sum "${casdoor_temporary}" | awk '{print $1}')"
printf '%s  %s\n%s  %s\n' \
  "${filmos_hash}" "$(basename "${filmos_final}")" \
  "${casdoor_hash}" "$(basename "${casdoor_final}")" \
  >"${manifest_temporary}"
if ! database_only_restore_test_requested; then
  attachments_hash="$(sha256sum "${attachments_temporary}" | awk '{print $1}')"
  printf '%s  %s\n' \
    "${attachments_hash}" "$(basename "${attachments_final}")" \
    >>"${manifest_temporary}"
fi
chmod 600 "${manifest_temporary}"
mv -- "${filmos_temporary}" "${filmos_final}"
mv -- "${casdoor_temporary}" "${casdoor_final}"
if ! database_only_restore_test_requested; then
  mv -- "${attachments_temporary}" "${attachments_final}"
fi
mv -- "${manifest_temporary}" "${manifest_final}"

find "${backup_directory}" \
  -maxdepth 1 \
  -type f \
  \( \
    -name 'filmos_*.dump' \
    -o -name 'casdoor_*.dump' \
    -o -name 'chat_attachments_*.tar.gz' \
    -o -name 'backup_*.sha256' \
  \) \
  -mtime "+$((retention_days - 1))" \
  -print \
  -delete

cleanup
trap - EXIT INT TERM
printf 'Backup complete: %s\n' "${manifest_final}"
