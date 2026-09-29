"""Test fixtures.

A throwaway database `<name>_test` is created on the server from DATABASE_URL (or
TEST_DATABASE_URL is used as-is), migrated to head, and dropped after the session.
Each test gets a session inside a transaction that is rolled back.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-0123456789abcdef")

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings, to_async_url
from app.crm.enums import Market, UserRole
from app.crm.models import Campaign, Client, User
from app.crm.security import create_access_token, hash_password
from app.db import get_session

API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _test_db_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return to_async_url(explicit)
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def _check_safe_to_drop(test_db: str) -> None:
    """The fixture DROPs the test database, so never let it point at a real one."""
    app_db = make_url(get_settings().database_url).database
    if test_db == app_db or "test" not in (test_db or "").lower():
        raise RuntimeError(
            f"Refusing to use {test_db!r} as the test database: it is dropped and recreated. "
            "Use a database name containing 'test' that differs from DATABASE_URL's."
        )


@pytest.fixture(scope="session")
async def db_url() -> AsyncIterator[str]:
    url = make_url(_test_db_url())
    _check_safe_to_drop(url.database)
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{url.database}"'))

    rendered = url.render_as_string(hide_password=False)
    cfg = Config(os.path.join(API_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(API_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
    # alembic's env.py runs its own event loop, so run it in a worker thread.

    await asyncio.to_thread(command.upgrade, cfg, "head")

    yield rendered

    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
    await admin.dispose()


@pytest.fixture
async def db_session(db_url: str) -> AsyncIterator[AsyncSession]:
    """Session inside an outer transaction; app-level commits become savepoints and everything
    is rolled back after the test."""
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    from app.main import app

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


# --- data factories ---------------------------------------------------------------------------

PASSWORD = "correct-horse-battery"
_PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture
def make_user(db_session: AsyncSession) -> Callable[..., Awaitable[User]]:
    async def _make(role: UserRole = UserRole.admin, email: str | None = None) -> User:
        user = User(
            email=email or f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=_PASSWORD_HASH,
            full_name=f"Test {role.value}",
            role=role,
        )
        db_session.add(user)
        await db_session.flush()
        return user

    return _make


def auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role.value)}"}


@pytest.fixture
async def admin_headers(make_user) -> dict[str, str]:
    return auth_header(await make_user(UserRole.admin))


@pytest.fixture
async def yp_client(db_session: AsyncSession) -> Client:
    c = Client(name="YP")
    db_session.add(c)
    await db_session.flush()
    return c


@pytest.fixture
async def campaign(db_session: AsyncSession, yp_client: Client) -> Campaign:
    c = Campaign(
        client_id=yp_client.id,
        name="YP SEO US (test)",
        market=Market.US,
        country_codes=["US", "CA"],
        default_timezone="America/New_York",
        languages=["en"],
        test_mode=True,
    )
    db_session.add(c)
    await db_session.flush()
    return c
