from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import bcrypt
import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models import UserRole
from app.services.identity_service import (
    ExternalIdentity,
    IdentityConflictError,
    resolve_external_user,
)

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    role: UserRole


class IdentityProviderUnavailableError(Exception):
    pass


class UnknownSigningKeyError(Exception):
    pass


class JwksCache:
    def __init__(self) -> None:
        self._keys: dict[str, jwt.PyJWK] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_key(self, key_id: str) -> Any:
        now = time.monotonic()
        cached = self._keys.get(key_id)
        if cached is not None and now < self._expires_at:
            return cached.key

        async with self._lock:
            now = time.monotonic()
            cached = self._keys.get(key_id)
            if cached is not None and now < self._expires_at:
                return cached.key
            await self._refresh()
            refreshed = self._keys.get(key_id)
            if refreshed is None:
                raise UnknownSigningKeyError
            return refreshed.key

    async def _refresh(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=settings.CASDOOR_HTTP_TIMEOUT_SECONDS) as client:
                response = await client.get(settings.CASDOOR_JWKS_URL)
                response.raise_for_status()
                payload = response.json()
            raw_keys = payload.get("keys")
            if not isinstance(raw_keys, list):
                raise ValueError("JWKS keys must be a list")
            parsed: dict[str, jwt.PyJWK] = {}
            for raw_key in raw_keys:
                if not isinstance(raw_key, dict):
                    continue
                key_id = raw_key.get("kid")
                if isinstance(key_id, str) and key_id:
                    parsed[key_id] = jwt.PyJWK.from_dict(raw_key)
            if not parsed:
                raise ValueError("JWKS contains no usable keys")
        except (httpx.HTTPError, ValueError, TypeError, jwt.PyJWKError) as exc:
            raise IdentityProviderUnavailableError from exc

        self._keys = parsed
        self._expires_at = time.monotonic() + settings.CASDOOR_JWKS_CACHE_SECONDS


_jwks_cache = JwksCache()


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录")


def _forbidden(message: str = "当前账号没有访问权限") -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, message)


def _decode_local_access_token(token: str) -> CurrentUser:
    try:
        payload = jwt.decode(
            token,
            settings.AUTH_SECRET,
            algorithms=["HS256"],
            options={"require": ["sub", "email", "role", "exp"]},
        )
        return CurrentUser(
            id=str(payload["sub"]),
            email=str(payload["email"]).strip().lower(),
            role=UserRole(str(payload["role"])),
        )
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise _unauthorized() from exc


def _extract_role(payload: dict[str, Any]) -> UserRole:
    raw_roles = payload.get("roles")
    if not isinstance(raw_roles, list):
        raise _forbidden("账号尚未分配 FilmOS 角色")

    role_names: set[str] = set()
    for raw_role in raw_roles:
        if isinstance(raw_role, str):
            role_names.add(raw_role)
        elif isinstance(raw_role, dict) and isinstance(raw_role.get("name"), str):
            role_names.add(raw_role["name"])

    mapped = {
        "filmos-owner": UserRole.OWNER,
        "filmos-operator": UserRole.OPERATOR,
    }
    accepted = {mapped[name] for name in role_names if name in mapped}
    if len(accepted) != 1:
        raise _forbidden("账号必须且只能分配一个 FilmOS 角色")
    return accepted.pop()


async def _decode_casdoor_access_token(token: str) -> ExternalIdentity:
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != settings.CASDOOR_ALLOWED_ALGORITHM:
            raise jwt.InvalidAlgorithmError
        key_id = header.get("kid")
        if not isinstance(key_id, str) or not key_id:
            raise jwt.InvalidTokenError
        signing_key = await _jwks_cache.get_key(key_id)
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[settings.CASDOOR_ALLOWED_ALGORITHM],
            audience=settings.CASDOOR_CLIENT_ID,
            issuer=settings.CASDOOR_ISSUER,
            options={"require": ["iss", "sub", "aud", "exp", "iat", "nbf"]},
        )
    except IdentityProviderUnavailableError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "身份服务暂时不可用，请稍后重试",
        ) from exc
    except (jwt.PyJWTError, UnknownSigningKeyError, KeyError, TypeError, ValueError) as exc:
        raise _unauthorized() from exc

    if payload.get("tokenType") != "access-token":
        raise _unauthorized()
    if payload.get("isForbidden") is True or payload.get("isDeleted") is True:
        raise _forbidden("当前账号已被停用")

    organization = payload.get("organization", payload.get("owner"))
    if organization != settings.CASDOOR_ORGANIZATION:
        raise _forbidden("账号不属于 FilmOS 组织")

    subject = payload.get("sub")
    email = payload.get("email")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise _unauthorized()
    if not isinstance(email, str) or not email.strip() or len(email) > 320:
        raise _forbidden("账号缺少有效邮箱")

    return ExternalIdentity(
        subject=subject,
        email=email.strip().lower(),
        role=_extract_role(payload),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")

    if settings.AUTH_PROVIDER == "local":
        return _decode_local_access_token(credentials.credentials)

    identity = await _decode_casdoor_access_token(credentials.credentials)
    try:
        user = await resolve_external_user(db, identity)
    except IdentityConflictError as exc:
        raise _forbidden("账号无法安全关联，请联系管理员") from exc
    return CurrentUser(id=user.id, email=user.email, role=user.role)


def require_roles(*allowed_roles: UserRole) -> Callable[..., Awaitable[CurrentUser]]:
    async def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise _forbidden()
        return user

    return dependency


require_owner = require_roles(UserRole.OWNER)
