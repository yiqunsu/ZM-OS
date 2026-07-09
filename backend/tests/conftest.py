import asyncpg
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.core.security import CurrentUser, get_current_user
from app.main import app
from app.models import Base

ADMIN_DSN = dict(user="filmos", password="filmos", database="filmos", host="localhost", port=5432)
TEST_DB_URL = "postgresql+asyncpg://filmos:filmos@localhost:5432/filmos_test"


async def _ensure_test_db() -> None:
    conn = await asyncpg.connect(**ADMIN_DSN)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'filmos_test'")
        if not exists:
            await conn.execute("CREATE DATABASE filmos_test")
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_schema():
    await _ensure_test_db()
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with session_factory() as session:
            yield session
        await trans.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    """Authenticated client — bypasses login so business-logic tests don't each need to sign in."""

    async def _override_get_db():
        yield db_session

    def _override_get_current_user():
        return CurrentUser(id="test-user", email="test@filmos.local", role="OWNER")

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def anon_client(db_session):
    """Client with no auth override — for testing the login flow and 401 behavior itself."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
