"""DNC lookups shared by import, manual lead creation and (Phase 3) the scheduler."""

import uuid
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.enums import DncScope
from app.crm.models import DncEntry


async def dnc_phones(
    session: AsyncSession, phones: Iterable[str], client_id: uuid.UUID | None
) -> set[str]:
    """Subset of `phones` (E.164) blocked globally or for `client_id`."""
    phones = list(set(phones))
    if not phones:
        return set()
    scope_filter = DncEntry.scope == DncScope.global_
    if client_id is not None:
        scope_filter = or_(
            scope_filter, (DncEntry.scope == DncScope.client) & (DncEntry.client_id == client_id)
        )
    blocked: set[str] = set()
    for i in range(0, len(phones), 5000):
        chunk = phones[i : i + 5000]
        rows = await session.scalars(
            select(DncEntry.phone_e164).where(DncEntry.phone_e164.in_(chunk), scope_filter)
        )
        blocked.update(rows)
    return blocked
