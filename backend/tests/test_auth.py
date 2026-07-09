from app.core.security import hash_password
from app.models import User, UserRole


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
