#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_command docker
load_environment

export CASDOOR_VERIFY_DATABASE_URL="postgresql://${CASDOOR_DB_USER}:${CASDOOR_DB_PASSWORD}@postgres:5432/${CASDOOR_DB}"
export CASDOOR_EXPECTED_ADMIN_EMAIL="${CASDOOR_ADMIN_EMAIL}"
export CASDOOR_EXPECTED_OWNER_NAME="${CASDOOR_OWNER_NAME}"
export CASDOOR_EXPECTED_OWNER_EMAIL="${CASDOOR_OWNER_EMAIL}"
export CASDOOR_EXPECTED_CALLBACK="${CASDOOR_REDIRECT_URI}"
export CASDOOR_EXPECTED_LOGOUT="${APP_PUBLIC_URL%/}/login"
export CASDOOR_EXPECTED_WECHAT_ENABLED="${WECHAT_LOGIN_ENABLED:-false}"
export CASDOOR_EXPECTED_WECHAT_APP_ID="${WECHAT_OPEN_APP_ID:-}"

compose run --rm -T \
  -e CASDOOR_VERIFY_DATABASE_URL \
  -e CASDOOR_ADMIN_PASSWORD \
  -e CASDOOR_EXPECTED_ADMIN_EMAIL \
  -e CASDOOR_EXPECTED_OWNER_NAME \
  -e CASDOOR_EXPECTED_OWNER_EMAIL \
  -e CASDOOR_EXPECTED_CALLBACK \
  -e CASDOOR_EXPECTED_LOGOUT \
  -e CASDOOR_EXPECTED_WECHAT_ENABLED \
  -e CASDOOR_EXPECTED_WECHAT_APP_ID \
  backend \
  python - <<'PY'
import asyncio
import json
import os

import asyncpg
import bcrypt


async def verify() -> None:
    connection = await asyncpg.connect(os.environ["CASDOOR_VERIFY_DATABASE_URL"])
    try:
        admin = await connection.fetchrow(
            'SELECT email, password FROM "user" WHERE owner = $1 AND name = $2',
            "built-in",
            "admin",
        )
        assert admin is not None, "built-in administrator is missing"
        assert admin["email"] == os.environ["CASDOOR_EXPECTED_ADMIN_EMAIL"].lower()
        password_hash = admin["password"].encode()
        assert bcrypt.checkpw(os.environ["CASDOOR_ADMIN_PASSWORD"].encode(), password_hash)
        assert not bcrypt.checkpw(b"123", password_hash), "default administrator password is still valid"

        owner_count = await connection.fetchval(
            'SELECT count(*) FROM "user" WHERE owner = $1 AND name = $2 AND email = $3',
            "filmos",
            os.environ["CASDOOR_EXPECTED_OWNER_NAME"],
            os.environ["CASDOOR_EXPECTED_OWNER_EMAIL"].lower(),
        )
        assert owner_count == 1, "initial FilmOS owner is missing"

        application = await connection.fetchrow(
            """
            SELECT enable_sign_up, token_format, token_signing_method,
                   expire_in_hours, refresh_expire_in_hours, redirect_uris,
                   providers, signin_methods
            FROM application
            WHERE owner = 'admin' AND name = 'app-filmos'
            """
        )
        assert application is not None, "FilmOS OIDC application is missing"
        assert application["enable_sign_up"] is False
        assert application["token_format"] == "JWT-Custom"
        assert application["token_signing_method"] == "RS256"
        assert application["expire_in_hours"] == 0.25
        assert application["refresh_expire_in_hours"] == 24
        redirect_uris = application["redirect_uris"]
        if isinstance(redirect_uris, str):
            redirect_uris = json.loads(redirect_uris)
        assert os.environ["CASDOOR_EXPECTED_CALLBACK"] in redirect_uris
        assert os.environ["CASDOOR_EXPECTED_LOGOUT"] in redirect_uris

        if os.environ["CASDOOR_EXPECTED_WECHAT_ENABLED"] == "true":
            provider = await connection.fetchrow(
                """
                SELECT category, type, sub_type, client_id
                FROM provider
                WHERE owner = 'admin' AND name = 'provider-wechat-web'
                """
            )
            assert provider is not None, "WeChat Web provider is missing"
            assert provider["category"] == "OAuth"
            assert provider["type"] == "WeChat"
            assert provider["sub_type"] == "Web"
            assert provider["client_id"] == os.environ["CASDOOR_EXPECTED_WECHAT_APP_ID"]

            provider_items = application["providers"]
            if isinstance(provider_items, str):
                provider_items = json.loads(provider_items)
            wechat_items = [
                item for item in provider_items
                if item.get("owner") == "admin" and item.get("name") == "provider-wechat-web"
            ]
            assert len(wechat_items) == 1, "FilmOS application is not bound to WeChat"
            wechat_item = wechat_items[0]
            assert wechat_item.get("canSignUp") is False
            assert wechat_item.get("canSignIn") is True
            assert wechat_item.get("canUnlink") is True
            assert wechat_item.get("bindingRule") == [], "automatic WeChat linking is enabled"

            signin_methods = application["signin_methods"]
            if isinstance(signin_methods, str):
                signin_methods = json.loads(signin_methods)
            method_rules = {item.get("name"): item.get("rule") for item in signin_methods}
            assert method_rules.get("Password") == "All", "password recovery login is missing"
            assert method_rules.get("WeChat") == "Tab", "WeChat QR signin method is missing"

        role_count = await connection.fetchval(
            """
            SELECT count(*) FROM role
            WHERE owner = 'filmos'
              AND name IN ('filmos-owner', 'filmos-operator')
              AND is_enabled = true
            """
        )
        assert role_count == 2, "FilmOS roles are missing or disabled"

        dcr_policy = await connection.fetchval(
            "SELECT dcr_policy FROM organization WHERE owner = 'admin' AND name = 'filmos'"
        )
        assert dcr_policy == "disabled", "dynamic client registration is not disabled"

        certificate_count = await connection.fetchval(
            """
            SELECT count(*) FROM cert
            WHERE owner = 'admin' AND name = 'cert-filmos'
              AND crypto_algorithm = 'RS256'
              AND certificate <> '' AND private_key <> ''
            """
        )
        assert certificate_count == 1, "FilmOS signing certificate is missing"
    finally:
        await connection.close()


asyncio.run(verify())
PY

grep -q '^initDataNewOnly = true$' "${REPO_ROOT}/.data/casdoor/app.conf" \
  || die "Casdoor initialization is not locked to create-only mode"

printf 'Casdoor bootstrap and default administrator rotation verified.\n'
