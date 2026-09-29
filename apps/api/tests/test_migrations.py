from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_extensions_enabled(db_session: AsyncSession) -> None:
    rows = await db_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pgcrypto')")
    )
    assert {r[0] for r in rows} == {"vector", "pgcrypto"}


async def test_gen_random_uuid_available(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT gen_random_uuid()"))
    assert result.scalar_one() is not None
