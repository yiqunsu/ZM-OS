#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command docker
load_environment

required_variables=(
  WEB_BIND_IP
  APP_SITE_ADDRESS
  AUTH_SITE_ADDRESS
  APP_PUBLIC_URL
  NEXTAUTH_URL
  CASDOOR_ISSUER
  CASDOOR_REDIRECT_URI
  POSTGRES_USER
  POSTGRES_PASSWORD
  POSTGRES_DB
  AUTH_SECRET
  CASDOOR_DB_USER
  CASDOOR_DB_PASSWORD
  CASDOOR_DB
  CASDOOR_CLIENT_ID
  CASDOOR_CLIENT_SECRET
  CASDOOR_ADMIN_EMAIL
  CASDOOR_ADMIN_PASSWORD
  CASDOOR_OWNER_NAME
  CASDOOR_OWNER_EMAIL
  CASDOOR_OWNER_PASSWORD
)

for variable_name in "${required_variables[@]}"; do
  [[ -n "${!variable_name:-}" ]] || die "${variable_name} must be set in ${ENV_FILE}"
  [[ "${!variable_name}" != *CHANGE_ME* ]] || die "${variable_name} still contains a CHANGE_ME placeholder"
done

[[ "${POSTGRES_USER}" =~ ^[a-z_][a-z0-9_]*$ ]] \
  || die "POSTGRES_USER must be a simple lowercase PostgreSQL identifier"
[[ "${POSTGRES_DB}" =~ ^[a-z_][a-z0-9_]*$ ]] \
  || die "POSTGRES_DB must be a simple lowercase PostgreSQL identifier"
[[ "${CASDOOR_DB_USER}" =~ ^[a-z_][a-z0-9_]*$ ]] \
  || die "CASDOOR_DB_USER must be a simple lowercase PostgreSQL identifier"
[[ "${CASDOOR_DB}" =~ ^[a-z_][a-z0-9_]*$ ]] \
  || die "CASDOOR_DB must be a simple lowercase PostgreSQL identifier"
[[ "${POSTGRES_DB}" != "${CASDOOR_DB}" ]] \
  || die "FilmOS and Casdoor must use different PostgreSQL databases"
[[ "${POSTGRES_USER}" != "${CASDOOR_DB_USER}" ]] \
  || die "FilmOS and Casdoor must use different PostgreSQL roles"
[[ "${POSTGRES_PASSWORD}" =~ ^[A-Za-z0-9._~-]{24,}$ ]] \
  || die "POSTGRES_PASSWORD must be at least 24 URI-safe characters; use: openssl rand -hex 24"
[[ "${CASDOOR_DB_PASSWORD}" =~ ^[A-Za-z0-9._~-]{24,}$ ]] \
  || die "CASDOOR_DB_PASSWORD must be at least 24 URI-safe characters; use: openssl rand -hex 24"
(( ${#AUTH_SECRET} >= 48 )) \
  || die "AUTH_SECRET must be at least 48 characters; use: openssl rand -hex 32"
[[ "${CASDOOR_CLIENT_ID}" =~ ^[A-Za-z0-9._~-]{16,100}$ ]] \
  || die "CASDOOR_CLIENT_ID must be 16-100 URI-safe characters"
(( ${#CASDOOR_CLIENT_SECRET} >= 48 )) \
  || die "CASDOOR_CLIENT_SECRET must be at least 48 characters"
(( ${#CASDOOR_ADMIN_PASSWORD} >= 20 )) \
  || die "CASDOOR_ADMIN_PASSWORD must be at least 20 characters"
[[ "${CASDOOR_ADMIN_PASSWORD}" != "123" ]] \
  || die "Casdoor's built-in default administrator password is forbidden"
(( ${#CASDOOR_OWNER_PASSWORD} >= 20 )) \
  || die "CASDOOR_OWNER_PASSWORD must be at least 20 characters"
[[ "${CASDOOR_ADMIN_EMAIL}" == *@*.* ]] \
  || die "CASDOOR_ADMIN_EMAIL must be a valid email address"
[[ "${CASDOOR_OWNER_EMAIL}" == *@*.* ]] \
  || die "CASDOOR_OWNER_EMAIL must be a valid email address"
[[ "${CASDOOR_OWNER_NAME}" =~ ^[a-z][a-z0-9_-]{2,63}$ ]] \
  || die "CASDOOR_OWNER_NAME must be a simple lowercase account name"

case "${WECHAT_LOGIN_ENABLED:-false}" in
  true)
    [[ "${WEB_BIND_IP}" == "0.0.0.0" ]] \
      || die "WeChat website login requires public HTTPS mode after ICP approval"
    [[ "${CASDOOR_ISSUER}" == "https://auth.zmorder.cn" ]] \
      || die "WeChat website login requires CASDOOR_ISSUER=https://auth.zmorder.cn"
    [[ -n "${WECHAT_OPEN_APP_ID:-}" ]] \
      || die "WECHAT_OPEN_APP_ID must be set when WECHAT_LOGIN_ENABLED=true"
    [[ -n "${WECHAT_OPEN_APP_SECRET:-}" ]] \
      || die "WECHAT_OPEN_APP_SECRET must be set when WECHAT_LOGIN_ENABLED=true"
    [[ "${WECHAT_OPEN_APP_ID}" != *CHANGE_ME* ]] \
      || die "WECHAT_OPEN_APP_ID still contains a CHANGE_ME placeholder"
    [[ "${WECHAT_OPEN_APP_SECRET}" != *CHANGE_ME* ]] \
      || die "WECHAT_OPEN_APP_SECRET still contains a CHANGE_ME placeholder"
    [[ "${WECHAT_OPEN_APP_ID}" =~ ^wx[A-Za-z0-9]{16}$ ]] \
      || die "WECHAT_OPEN_APP_ID must be a WeChat Open Platform website AppID"
    (( ${#WECHAT_OPEN_APP_SECRET} >= 24 )) \
      || die "WECHAT_OPEN_APP_SECRET is unexpectedly short"
    ;;
  false)
    ;;
  *)
    die "WECHAT_LOGIN_ENABLED must be true or false"
    ;;
esac

case "${AGENT_RUNTIME:-openclaw}" in
  openclaw)
    [[ -n "${OPENCLAW_GATEWAY_TOKEN:-}" ]] \
      || die "OPENCLAW_GATEWAY_TOKEN must be set when AGENT_RUNTIME=openclaw"
    [[ "${OPENCLAW_GATEWAY_TOKEN}" != *CHANGE_ME* ]] \
      || die "OPENCLAW_GATEWAY_TOKEN still contains a CHANGE_ME placeholder"
    (( ${#OPENCLAW_GATEWAY_TOKEN} >= 64 )) \
      || die "OPENCLAW_GATEWAY_TOKEN must contain at least 64 characters; use: openssl rand -hex 32"
    [[ -n "${QWEN_API_KEY:-}" ]] \
      || die "QWEN_API_KEY must be set when AGENT_RUNTIME=openclaw"
    [[ "${QWEN_API_KEY}" != *CHANGE_ME* ]] \
      || die "QWEN_API_KEY still contains a CHANGE_ME placeholder"
    ;;
  langgraph)
    [[ -n "${LLM_API_KEY:-}" ]] \
      || die "LLM_API_KEY must be set when AGENT_RUNTIME=langgraph"
    [[ "${LLM_API_KEY}" != *CHANGE_ME* ]] \
      || die "LLM_API_KEY still contains a CHANGE_ME placeholder"
    ;;
  *)
    die "AGENT_RUNTIME must be openclaw or langgraph"
    ;;
esac

case "${WEB_BIND_IP}" in
  127.0.0.1)
    [[ "${APP_SITE_ADDRESS}" == "http://app.filmos.test" ]] \
      || die "Private mode requires APP_SITE_ADDRESS=http://app.filmos.test"
    [[ "${AUTH_SITE_ADDRESS}" == "http://auth.filmos.test" ]] \
      || die "Private mode requires AUTH_SITE_ADDRESS=http://auth.filmos.test"
    [[ "${APP_PUBLIC_URL}" == "http://app.filmos.test:8080" ]] \
      || die "Private mode requires APP_PUBLIC_URL=http://app.filmos.test:8080"
    [[ "${NEXTAUTH_URL}" == "${APP_PUBLIC_URL}" ]] \
      || die "Private mode requires NEXTAUTH_URL to equal APP_PUBLIC_URL"
    [[ "${CASDOOR_ISSUER}" == "http://auth.filmos.test:8080" ]] \
      || die "Private mode requires CASDOOR_ISSUER=http://auth.filmos.test:8080"
    ;;
  0.0.0.0)
    [[ "${APP_SITE_ADDRESS}" == "app.zmorder.cn" ]] \
      || die "Public mode requires APP_SITE_ADDRESS=app.zmorder.cn"
    [[ "${AUTH_SITE_ADDRESS}" == "auth.zmorder.cn" ]] \
      || die "Public mode requires AUTH_SITE_ADDRESS=auth.zmorder.cn"
    [[ "${APP_PUBLIC_URL}" == "https://app.zmorder.cn" ]] \
      || die "Public mode requires APP_PUBLIC_URL=https://app.zmorder.cn"
    [[ "${NEXTAUTH_URL}" == "${APP_PUBLIC_URL}" ]] \
      || die "Public mode requires NEXTAUTH_URL to equal APP_PUBLIC_URL"
    [[ "${CASDOOR_ISSUER}" == "https://auth.zmorder.cn" ]] \
      || die "Public mode requires CASDOOR_ISSUER=https://auth.zmorder.cn"
    ;;
  *)
    die "WEB_BIND_IP must be 127.0.0.1 (ICP pending) or 0.0.0.0 (public after ICP approval)"
    ;;
esac

[[ "${CASDOOR_REDIRECT_URI}" == "${APP_PUBLIC_URL}/api/auth/callback/casdoor" ]] \
  || die "CASDOOR_REDIRECT_URI must exactly match APP_PUBLIC_URL/api/auth/callback/casdoor"

if command -v stat >/dev/null 2>&1; then
  environment_mode="$(stat -c '%a' "${ENV_FILE}" 2>/dev/null || true)"
  if [[ -n "${environment_mode}" && "${environment_mode}" != "600" ]]; then
    printf 'WARNING: set restrictive permissions with: chmod 600 %q\n' "${ENV_FILE}" >&2
  fi
fi

compose config --quiet

printf 'Production environment is valid (%s mode).\n' \
  "$([[ "${WEB_BIND_IP}" == "127.0.0.1" ]] && printf private || printf public)"
