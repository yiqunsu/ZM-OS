#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command docker
require_command python3
load_environment

export CASDOOR_RUNTIME_DIR="${REPO_ROOT}/.data/casdoor"
python3 "${SCRIPT_DIR}/prepare-casdoor.py"

role_exists="$(
  compose exec -T postgres psql \
    --username "${POSTGRES_USER}" \
    --dbname postgres \
    --tuples-only \
    --no-align \
    --command "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${CASDOOR_DB_USER}');" \
    | tr -d '[:space:]'
)"

if [[ "${role_exists}" != "t" ]]; then
  compose exec -T postgres psql \
    --username "${POSTGRES_USER}" \
    --dbname postgres \
    --set ON_ERROR_STOP=1 \
    --command "CREATE ROLE ${CASDOOR_DB_USER} LOGIN PASSWORD '${CASDOOR_DB_PASSWORD}';"
else
  compose exec -T postgres psql \
    --username "${POSTGRES_USER}" \
    --dbname postgres \
    --set ON_ERROR_STOP=1 \
    --command "ALTER ROLE ${CASDOOR_DB_USER} WITH LOGIN PASSWORD '${CASDOOR_DB_PASSWORD}';"
fi

database_exists="$(
  compose exec -T postgres psql \
    --username "${POSTGRES_USER}" \
    --dbname postgres \
    --tuples-only \
    --no-align \
    --command "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = '${CASDOOR_DB}');" \
    | tr -d '[:space:]'
)"

if [[ "${database_exists}" != "t" ]]; then
  compose exec -T postgres createdb \
    --username "${POSTGRES_USER}" \
    --owner "${CASDOOR_DB_USER}" \
    "${CASDOOR_DB}"
fi

compose exec -T postgres psql \
  --username "${POSTGRES_USER}" \
  --dbname postgres \
  --set ON_ERROR_STOP=1 \
  --command "ALTER DATABASE ${CASDOOR_DB} OWNER TO ${CASDOOR_DB_USER};"

printf 'Casdoor PostgreSQL role and database are ready.\n'
