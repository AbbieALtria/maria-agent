"""Audit log helper (NFR-4: DNC changes, appointment changes, playbook activation, …)."""

import uuid
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.models import AuditLog, User


def snapshot(obj: Any, fields: list[str] | None = None) -> dict[str, Any]:
    """JSON-safe dict of an ORM row's columns (or the given subset)."""
    cols = fields or [c.key for c in obj.__table__.columns]
    return jsonable_encoder({c: getattr(obj, c) for c in cols if c != "password_hash"})


def audit(
    session: AsyncSession,
    actor: User | None,
    action: str,
    entity: str,
    entity_id: uuid.UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            action=action,
            entity=entity,
            entity_id=entity_id,
            before=jsonable_encoder(before) if before is not None else None,
            after=jsonable_encoder(after) if after is not None else None,
        )
    )
