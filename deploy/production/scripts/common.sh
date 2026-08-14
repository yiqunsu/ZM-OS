#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${DEPLOY_DIR}/../.." && pwd)"
COMPOSE_FILE="${FILMOS_COMPOSE_FILE:-${DEPLOY_DIR}/compose.yml}"
ENV_FILE="${FILMOS_ENV_FILE:-${DEPLOY_DIR}/.env.production}"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

load_environment() {
  [[ -f "${ENV_FILE}" ]] || die "Missing production environment file: ${ENV_FILE}"

  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
}

compose() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

database_only_restore_test_requested() {
  [[ "${FILMOS_RESTORE_DATABASE_ONLY_FOR_TESTS:-false}" == "true" ]]
}

require_disposable_restore_database() {
  local database="$1"

  database_only_restore_test_requested || return 0
  [[ "${database}" == *_restore_test ]] \
    || die "Database-only restore mode is restricted to disposable *_restore_test databases"
}

wait_for_service_health() {
  local service="$1"
  local timeout_seconds="${2:-120}"
  local container_id status started_at

  container_id="$(compose ps -q "${service}")"
  [[ -n "${container_id}" ]] || die "No container found for service: ${service}"
  started_at="$(date +%s)"

  while true; do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
    case "${status}" in
      healthy | running)
        printf '%s is %s\n' "${service}" "${status}"
        return 0
        ;;
      unhealthy | exited | dead)
        compose logs --tail=100 "${service}" >&2 || true
        die "${service} entered state: ${status}"
        ;;
    esac

    if (( $(date +%s) - started_at >= timeout_seconds )); then
      compose logs --tail=100 "${service}" >&2 || true
      die "Timed out waiting for ${service} health (last state: ${status})"
    fi
    sleep 2
  done
}
