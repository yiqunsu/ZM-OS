import asyncio
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import security
from app.core.config import settings
from app.core.security import hash_password
from app.models import User, UserRole
from app.services.identity_service import ExternalIdentity, resolve_external_user

TEST_DB_URL = "postgresql+asyncpg://filmos:filmos@localhost:5432/filmos_test"


async def _create_user(db_session, email="owner@filmos.local", password="secret123"):
    user = User(email=email, password_hash=hash_password(password), role=UserRole.OWNER)
    db_session.add(user)
    await db_session.commit()
    return user


async def test_login_succeeds_with_correct_credentials(anon_client, db_session):
    await _create_user(db_session)
    res = await anon_client.post(
        "/api/auth/login", json={"email": "owner@filmos.local", "password": "secret123"}
    )
    assert res.status_code == 200
    assert res.json()["role"] == "OWNER"


async def test_login_rejects_wrong_password(anon_client, db_session):
    await _create_user(db_session)
    res = await anon_client.post("/api/auth/login", json={"email": "owner@filmos.local", "password": "wrong"})
    assert res.status_code == 401


async def test_login_rejects_unknown_email(anon_client):
    res = await anon_client.post("/api/auth/login", json={"email": "nobody@filmos.local", "password": "x"})
    assert res.status_code == 401


async def test_protected_endpoint_requires_auth(anon_client):
    res = await anon_client.get("/api/customers")
    assert res.status_code == 401


async def test_protected_endpoint_rejects_garbage_token(anon_client):
    res = await anon_client.get("/api/customers", headers={"Authorization": "Bearer not-a-real-token"})
    assert res.status_code == 401


@pytest.fixture
def casdoor_token(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    async def get_key(_key_id: str):
        return private_key.public_key()

    monkeypatch.setattr(settings, "AUTH_PROVIDER", "casdoor")
    monkeypatch.setattr(settings, "CASDOOR_ISSUER", "https://auth.example.test")
    monkeypatch.setattr(settings, "CASDOOR_CLIENT_ID", "filmos-client")
    monkeypatch.setattr(settings, "CASDOOR_ORGANIZATION", "filmos")
    monkeypatch.setattr(security._jwks_cache, "get_key", get_key)

    def issue(**overrides):
        now = int(time.time())
        payload = {
            "iss": settings.CASDOOR_ISSUER,
            "sub": "casdoor-subject",
            "aud": settings.CASDOOR_CLIENT_ID,
            "iat": now,
            "nbf": now,
            "exp": now + 900,
            "tokenType": "access-token",
            "owner": settings.CASDOOR_ORGANIZATION,
            "email": "owner@example.com",
            "roles": ["filmos-owner"],
            "isForbidden": False,
            "isDeleted": False,
        }
        payload.update(overrides)
        return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-key"})

    return issue


async def test_casdoor_login_links_existing_user_without_changing_id(
    anon_client, db_session, casdoor_token
):
    user = User(
        id="existing-owner-id",
        email="Owner@Example.com",
        password_hash=hash_password("legacy-password"),
        role=UserRole.OWNER,
    )
    db_session.add(user)
    await db_session.commit()

    token = casdoor_token()
    res = await anon_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 200
    assert res.json() == {
        "id": "existing-owner-id",
        "email": "owner@example.com",
        "role": "OWNER",
    }
    await db_session.refresh(user)
    assert user.external_subject == "casdoor-subject"


async def test_casdoor_login_provisions_operator_once(anon_client, db_session, casdoor_token):
    token = casdoor_token(
        sub="new-operator-subject",
        email="operator@example.com",
        roles=["filmos-operator"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    first = await anon_client.get("/api/auth/me", headers=headers)
    second = await anon_client.get("/api/auth/me", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["role"] == "OPERATOR"


async def test_concurrent_first_login_returns_one_stable_user(casdoor_token):
    del casdoor_token
    identity = ExternalIdentity(
        subject="concurrent-casdoor-subject",
        email="concurrent-operator@example.com",
        role=UserRole.OPERATOR,
    )
    engine = create_async_engine(TEST_DB_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def resolve_once() -> str:
        async with session_factory() as session:
            user = await resolve_external_user(session, identity)
            return user.id

    try:
        first_id, second_id = await asyncio.gather(resolve_once(), resolve_once())
        assert first_id == second_id
    finally:
        async with session_factory() as session:
            await session.execute(delete(User).where(User.external_subject == identity.subject))
            await session.commit()
        await engine.dispose()


async def test_linking_rejects_email_owned_by_another_subject(
    anon_client, db_session, casdoor_token
):
    db_session.add(
        User(
            email="collision@example.com",
            external_subject="another-subject",
            password_hash=None,
            role=UserRole.OPERATOR,
        )
    )
    await db_session.commit()

    token = casdoor_token(sub="new-subject", email="collision@example.com")
    res = await anon_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"aud": "another-client"}, 401),
        ({"iss": "https://issuer.example.invalid"}, 401),
        ({"tokenType": "refresh-token"}, 401),
        ({"owner": "another-organization"}, 403),
        ({"roles": []}, 403),
        ({"roles": ["filmos-owner", "filmos-operator"]}, 403),
        ({"isForbidden": True}, 403),
        ({"isDeleted": True}, 403),
        ({"exp": 1}, 401),
        ({"roles": [{"name": "filmos-owner"}]}, 200),
    ],
)
async def test_casdoor_token_and_role_validation(
    anon_client, casdoor_token, overrides, expected_status
):
    token = casdoor_token(**overrides)
    res = await anon_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == expected_status


async def test_unknown_signing_key_is_unauthorized(
    anon_client, casdoor_token, monkeypatch
):
    async def unknown_key(_key_id: str):
        raise security.UnknownSigningKeyError

    monkeypatch.setattr(security._jwks_cache, "get_key", unknown_key)
    res = await anon_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {casdoor_token()}"},
    )
    assert res.status_code == 401


async def test_unavailable_jwks_returns_temporary_failure(
    anon_client, casdoor_token, monkeypatch
):
    async def unavailable(_key_id: str):
        raise security.IdentityProviderUnavailableError

    monkeypatch.setattr(security._jwks_cache, "get_key", unavailable)
    res = await anon_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {casdoor_token()}"},
    )
    assert res.status_code == 503


async def test_jwks_cache_refreshes_only_after_expiry(monkeypatch):
    cache = security.JwksCache()
    refresh_calls = 0
    first_key = object()
    rotated_key = object()

    async def refresh():
        nonlocal refresh_calls
        refresh_calls += 1
        key = first_key if refresh_calls == 1 else rotated_key
        cache._keys = {"key-id": SimpleNamespace(key=key)}
        cache._expires_at = time.monotonic() + 60

    monkeypatch.setattr(cache, "_refresh", refresh)

    assert await cache.get_key("key-id") is first_key
    assert await cache.get_key("key-id") is first_key
    assert refresh_calls == 1

    cache._expires_at = 0
    assert await cache.get_key("key-id") is rotated_key
    assert refresh_calls == 2


async def test_wrongly_signed_casdoor_token_is_unauthorized(anon_client, casdoor_token):
    valid_token = casdoor_token()
    payload = jwt.decode(valid_token, options={"verify_signature": False})
    another_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_token = jwt.encode(
        payload,
        another_private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    res = await anon_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {wrong_token}"}
    )
    assert res.status_code == 401


async def test_operator_can_read_but_cannot_write_master_data(anon_client, casdoor_token):
    token = casdoor_token(
        sub="operator-rbac-subject",
        email="rbac-operator@example.com",
        roles=["filmos-operator"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    read_res = await anon_client.get("/api/customers", headers=headers)
    write_res = await anon_client.post(
        "/api/customers",
        headers=headers,
        json={"company": "不应创建", "contact": "测试", "notes": None},
    )

    assert read_res.status_code == 200
    assert write_res.status_code == 403


async def test_owner_can_write_master_data(anon_client, casdoor_token):
    token = casdoor_token(sub="owner-rbac-subject", email="rbac-owner@example.com")
    res = await anon_client.post(
        "/api/customers",
        headers={"Authorization": f"Bearer {token}"},
        json={"company": "可创建客户", "contact": "测试", "notes": None},
    )
    assert res.status_code == 201


async def test_casdoor_mode_disables_password_login(anon_client, casdoor_token):
    del casdoor_token
    res = await anon_client.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": "legacy-password"},
    )
    assert res.status_code == 404
