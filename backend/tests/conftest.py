"""
Root conftest: environment setup + shared fixtures for all test layers.

DB/infrastructure fixtures live here but are NOT autouse, so unit tests
(which never request them) never trigger testcontainers or PostgreSQL.
"""
import os
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import patch

# ── Must appear before any app import ──────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test-dummy-key-not-real")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
# ────────────────────────────────────────────────────────────────────────────

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

import app.db.database as _db_module
import app.main as _main_module
from app.api.deps import get_current_user
from app.db.database import Base, get_db
from app.db.models import User
from app.main import app


# ---------------------------------------------------------------------------
# Session-scoped: one PostgreSQL container per pytest session.
# Only starts when a test (directly or transitively) requests `db_engine`.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def test_db_url(pg_container) -> str:
    raw = pg_container.get_connection_url()
    url = raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    url = url.replace("postgresql://", "postgresql+asyncpg://")
    return url


@pytest.fixture(scope="session")
async def db_engine(test_db_url):
    engine = create_async_engine(test_db_url, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="session")
def TestSessionLocal(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Session-scoped: patch the production engine so that the FastAPI lifespan
# uses our test engine when an AsyncClient is created.
# NOT autouse — only activates when 'client' or 'unauth_client' is used.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
async def _patch_app_engine(db_engine, TestSessionLocal):
    _main_module.engine = db_engine
    _db_module.engine = db_engine
    _db_module.AsyncSessionLocal = TestSessionLocal
    yield


# ---------------------------------------------------------------------------
# Per-test: fresh session (rolled back / cleaned after each test)
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session(TestSessionLocal) -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Reusable test user (created fresh per test, cleaned by _clean_tables)
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        google_id=f"google-uid-{uuid.uuid4().hex[:8]}",
        email="testuser@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Authenticated HTTP client.
# Depends on `_patch_app_engine` so testcontainers only starts when needed.
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(
    db_session: AsyncSession,
    test_user: User,
    _patch_app_engine,  # ensures engine is patched before AsyncClient is created
) -> AsyncGenerator[AsyncClient, None]:
    async def _get_db():
        yield db_session

    async def _get_current_user():
        return test_user

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_current_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Reset rate-limiter storage between tests so per-minute/per-day counters
# from one test don't bleed into the next.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    from app.security.rate_limiter import limiter
    yield
    limiter._storage.reset()


# ---------------------------------------------------------------------------
# Unauthenticated client (no auth override — only DB override)
# ---------------------------------------------------------------------------


@pytest.fixture
async def unauth_client(
    db_session: AsyncSession,
    _patch_app_engine,
) -> AsyncGenerator[AsyncClient, None]:
    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
