"""Test fixtures.

A throwaway database `<name>_test` is created on the server from DATABASE_URL (or
TEST_DATABASE_URL is used as-is), migrated to head, and dropped after the session.
Each test gets a session inside a transaction that is rolled back.
"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import get_settings, to_async_url

API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _test_db_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return to_async_url(explicit)
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
async def db_url() -> AsyncIterator[str]:
    url = make_url(_test_db_url())
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
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
