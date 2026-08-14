#!/usr/bin/env python3
"""Generate Casdoor runtime files without committing credentials."""

from __future__ import annotations

import json
import os
from pathlib import Path


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"ERROR: {name} is required")
    return value


def enabled(name: str) -> bool:
    value = os.environ.get(name, "false").strip().lower()
    if value not in {"true", "false"}:
        raise SystemExit(f"ERROR: {name} must be true or false")
    return value == "true"


runtime_dir = Path(required("CASDOOR_RUNTIME_DIR"))
runtime_dir.mkdir(parents=True, exist_ok=True)
runtime_dir.chmod(0o700)

initialized = (runtime_dir / ".initialized").exists()
origin = required("CASDOOR_ISSUER").rstrip("/")

app_conf = f"""appname = casdoor
httpport = 8000
runmode = prod
copyrequestbody = true
driverName = postgres
dataSourceName = user={required('CASDOOR_DB_USER')} password={required('CASDOOR_DB_PASSWORD')} host=postgres port=5432 sslmode=disable dbname={required('CASDOOR_DB')}
dbName = {required('CASDOOR_DB')}
tableNamePrefix =
showSql = false
redisEndpoint =
defaultStorageProvider =
isCloudIntranet = false
authState = filmos-production
verificationCodeTimeout = 10
initScore = 0
logPostOnly = true
isUsernameLowered = true
origin = {origin}
originFrontend = {origin}
staticBaseUrl = https://cdn.casbin.org
isDemoMode = false
batchSize = 100
showGithubCorner = false
forceLanguage = zh
defaultLanguage = zh
defaultApplication = app-filmos
enableErrorMask = true
enableGzip = true
logConfig = {{"adapter":"console"}}
initDataNewOnly = {'true' if initialized else 'false'}
initDataFile = /init_data.json
"""

owner_name = required("CASDOOR_OWNER_NAME")
owner_email = required("CASDOOR_OWNER_EMAIL").strip().lower()
current_app_url = required("APP_PUBLIC_URL").rstrip("/")
wechat_login_enabled = enabled("WECHAT_LOGIN_ENABLED")
wechat_provider_name = "provider-wechat-web"
wechat_providers: list[dict[str, object]] = []
application_providers: list[dict[str, object]] = []
signin_methods = [{"name": "Password", "displayName": "密码", "rule": "All"}]

if wechat_login_enabled:
    wechat_app_id = required("WECHAT_OPEN_APP_ID")
    wechat_app_secret = required("WECHAT_OPEN_APP_SECRET")
    if "CHANGE_ME" in wechat_app_id or "CHANGE_ME" in wechat_app_secret:
        raise SystemExit("ERROR: WeChat credentials still contain a CHANGE_ME placeholder")
    wechat_providers.append(
        {
            "owner": "admin",
            "name": wechat_provider_name,
            "displayName": "微信扫码登录",
            "category": "OAuth",
            "type": "WeChat",
            "subType": "Web",
            "clientId": wechat_app_id,
            "clientSecret": wechat_app_secret,
            "scopes": "snsapi_login",
            "disableSsl": False,
            "signName": "open",
            "userMapping": {},
        }
    )
    application_providers.append(
        {
            "owner": "admin",
            "name": wechat_provider_name,
            "canSignUp": False,
            "canSignIn": True,
            "canUnlink": True,
            # Never fall back to Casdoor's default Email/Phone/Name linking.
            "bindingRule": [],
            "prompted": False,
            "signupGroup": "",
            "rule": "None",
        }
    )
    signin_methods.append(
        {"name": "WeChat", "displayName": "微信扫码", "rule": "Tab"}
    )
allowed_redirects = [
    required("CASDOOR_REDIRECT_URI"),
    f"{current_app_url}/login",
    "https://app.zmorder.cn/api/auth/callback/casdoor",
    "https://app.zmorder.cn/login",
]
# Preserve order while removing duplicates in public mode.
allowed_redirects = list(dict.fromkeys(allowed_redirects))

init_data = {
    "organizations": [
        {
            "owner": "admin",
            "name": "filmos",
            "displayName": "FilmOS",
            "websiteUrl": current_app_url,
            "passwordType": "bcrypt",
            "passwordOptions": ["AtLeast8", "Aa123"],
            "countryCodes": ["CN"],
            "defaultApplication": "app-filmos",
            "languages": ["zh", "en"],
            "initScore": 0,
            "enableSoftDeletion": False,
            "isProfilePublic": False,
            "useEmailAsUsername": True,
            "disableSignin": False,
            "dcrPolicy": "disabled",
        }
    ],
    "applications": [
        {
            "owner": "admin",
            "name": "app-filmos",
            "displayName": "FilmOS",
            "category": "Default",
            "type": "All",
            "scopes": [],
            "homepageUrl": current_app_url,
            "organization": "filmos",
            "cert": "cert-filmos",
            "enablePassword": True,
            "enableSignUp": False,
            "enableGuestSignin": False,
            "disableSignin": False,
            "enableSigninSession": True,
            "providers": application_providers,
            "signinMethods": signin_methods,
            "grantTypes": ["authorization_code", "refresh_token"],
            "clientId": required("CASDOOR_CLIENT_ID"),
            "clientSecret": required("CASDOOR_CLIENT_SECRET"),
            "redirectUris": allowed_redirects,
            "tokenFormat": "JWT-Custom",
            "tokenSigningMethod": "RS256",
            "tokenFields": ["Email", "Owner", "DisplayName", "IsForbidden", "IsDeleted"],
            "tokenAttributes": [
                {
                    "name": "roles",
                    "category": "Existing Field",
                    "value": "Roles",
                    "type": "Array",
                }
            ],
            "expireInHours": 0.25,
            "refreshExpireInHours": 24,
            "cookieExpireInHours": 8,
            "failedSigninLimit": 5,
            "failedSigninFrozenTime": 15,
        }
    ],
    "providers": wechat_providers,
    "users": [
        {
            "owner": "built-in",
            "name": "admin",
            "type": "normal-user",
            "password": required("CASDOOR_ADMIN_PASSWORD"),
            "displayName": "Casdoor Administrator",
            "email": required("CASDOOR_ADMIN_EMAIL").strip().lower(),
            "isAdmin": True,
            "isForbidden": False,
            "isDeleted": False,
            "signupApplication": "app-built-in",
            "address": [],
            "addresses": [],
            "groups": [],
            "properties": {},
        },
        {
            "owner": "filmos",
            "name": owner_name,
            "type": "normal-user",
            "password": required("CASDOOR_OWNER_PASSWORD"),
            "displayName": "FilmOS Owner",
            "email": owner_email,
            "isAdmin": True,
            "isForbidden": False,
            "isDeleted": False,
            "signupApplication": "app-filmos",
            "address": [],
            "addresses": [],
            "groups": [],
            "properties": {},
        },
    ],
    "certs": [
        {
            "owner": "admin",
            "name": "cert-filmos",
            "displayName": "FilmOS OIDC Signing Certificate",
            "scope": "JWT",
            "type": "x509",
            "cryptoAlgorithm": "RS256",
            "bitSize": 2048,
            "expireInYears": 10,
            "certificate": "",
            "privateKey": "",
        }
    ],
    "roles": [
        {
            "owner": "filmos",
            "name": "filmos-owner",
            "displayName": "FilmOS Owner",
            "description": "FilmOS business owner",
            "isEnabled": True,
            "users": [f"filmos/{owner_name}"],
            "groups": [],
            "roles": [],
            "domains": [],
        },
        {
            "owner": "filmos",
            "name": "filmos-operator",
            "displayName": "FilmOS Operator",
            "description": "FilmOS production operator",
            "isEnabled": True,
            "users": [],
            "groups": [],
            "roles": [],
            "domains": [],
        },
    ],
}


def write_private(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


write_private(runtime_dir / "app.conf", app_conf)
write_private(
    runtime_dir / "init_data.json",
    json.dumps(init_data, ensure_ascii=False, indent=2) + "\n",
)
print(f"Casdoor runtime configuration prepared (initialized={initialized}).")
