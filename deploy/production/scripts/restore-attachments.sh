#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command docker
require_command tar
load_environment

backup_path="${1:-}"
confirmation="${2:-}"

[[ -n "${backup_path}" ]] \
  || die "Usage: restore-attachments.sh <chat-attachments-backup.tar.gz> --confirm-attachment-replacement"
[[ "${confirmation}" == "--confirm-attachment-replacement" ]] \
  || die "Restore replaces all chat attachments. Re-run with --confirm-attachment-replacement"
[[ -f "${backup_path}" && -r "${backup_path}" ]] \
  || die "Backup file is not readable: ${backup_path}"
[[ "$(basename "${backup_path}")" == chat_attachments_*.tar.gz ]] \
  || die "Attachment restore requires a chat_attachments_*.tar.gz backup"
tar -tzf "${backup_path}" >/dev/null \
  || die "Attachment backup failed archive validation"

printf 'Stopping FilmOS application writers...\n'
compose stop caddy frontend backend || true

restore_failed() {
  printf 'Attachment restore failed. Application services remain stopped; inspect the errors before restarting.\n' >&2
}
trap restore_failed ERR

compose run --rm --no-deps -T backend python -c '
import shutil
import sys
import tarfile
from pathlib import Path

root = Path("/app/data/chat-attachments")
staging = root / ".restore-staging"
if staging.exists():
    shutil.rmtree(staging)
staging.mkdir(parents=True)
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
    for member in archive:
        path = Path(member.name)
        if path.is_absolute() or ".." in path.parts or path.parts[:1] != ("chat-attachments",):
            raise RuntimeError("unsafe attachment archive path")
        if member.isdir():
            continue
        member.name = str(Path(*path.parts[1:]))
        archive.extract(member, staging, filter="data")
for child in list(root.iterdir()):
    if child == staging:
        continue
    if child.is_dir():
        shutil.rmtree(child)
    else:
        child.unlink()
for child in list(staging.iterdir()):
    child.replace(root / child.name)
staging.rmdir()
' <"${backup_path}"

compose up -d backend frontend caddy
wait_for_service_health backend 120
wait_for_service_health frontend 120
wait_for_service_health caddy 60

trap - ERR
printf 'Chat attachment restore complete and FilmOS services are healthy.\n'
