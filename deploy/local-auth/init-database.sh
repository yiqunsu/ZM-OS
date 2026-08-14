#!/usr/bin/env bash

set -Eeuo pipefail

for name in CASDOOR_DB CASDOOR_DB_USER CASDOOR_DB_PASSWORD; do
  [[ -n "${!name:-}" ]] || {
    printf 'ERROR: %s is required\n' "${name}" >&2
    exit 1
  }
done

[[ "${CASDOOR_DB}" =~ ^[a-z_][a-z0-9_]*$ ]] \
  || { printf 'ERROR: invalid CASDOOR_DB identifier\n' >&2; exit 1; }
[[ "${CASDOOR_DB_USER}" =~ ^[a-z_][a-z0-9_]*$ ]] \
  || { printf 'ERROR: invalid CASDOOR_DB_USER identifier\n' >&2; exit 1; }

role_exists="$(psql --tuples-only --no-align --set role="${CASDOOR_DB_USER}" <<'SQL'
SELECT 1 FROM pg_roles WHERE rolname = :'role';
SQL
)"
if [[ "${role_exists}" != "1" ]]; then
  psql --set role="${CASDOOR_DB_USER}" --set password="${CASDOOR_DB_PASSWORD}" <<'SQL'
CREATE ROLE :"role" LOGIN PASSWORD :'password';
SQL
else
  psql --set role="${CASDOOR_DB_USER}" --set password="${CASDOOR_DB_PASSWORD}" <<'SQL'
ALTER ROLE :"role" PASSWORD :'password';
SQL
fi

database_exists="$(psql --tuples-only --no-align --set database="${CASDOOR_DB}" <<'SQL'
SELECT 1 FROM pg_database WHERE datname = :'database';
SQL
)"
if [[ "${database_exists}" != "1" ]]; then
  createdb --owner "${CASDOOR_DB_USER}" "${CASDOOR_DB}"
fi

psql --set database="${CASDOOR_DB}" --set role="${CASDOOR_DB_USER}" <<'SQL'
ALTER DATABASE :"database" OWNER TO :"role";
SQL
