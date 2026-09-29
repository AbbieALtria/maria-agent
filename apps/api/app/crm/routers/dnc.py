import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, update

from app.crm.audit import audit, snapshot
from app.crm.deps import Admin, AnyUser, DbSession
from app.crm.enums import DncScope, LeadStatus
from app.crm.models import Campaign, Client, DncEntry, Lead
from app.crm.schemas import DncCheckIn, DncCheckOut, DncIn, DncOut, Page
from app.crm.services.dnc import dnc_phones
from maria_shared.phone import InvalidPhoneError, normalize_phone

router = APIRouter(prefix="/dnc", tags=["dnc"])


@router.get("", response_model=Page[DncOut])
async def list_dnc(
    session: DbSession,
    _: AnyUser,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> Page[DncOut]:
    stmt = select(DncEntry)
    if q:
        digits = "".join(c for c in q if c.isdigit())
        stmt = stmt.where(DncEntry.phone_e164.contains(digits or q))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await session.scalars(
        stmt.order_by(DncEntry.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return Page[DncOut](
        items=[DncOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size
    )


async def add_dnc(
    session: DbSession,
    phone_e164: str,
    scope: DncScope,
    client_id: uuid.UUID | None,
    reason: str | None,
    source: str,
    actor,
) -> tuple[DncEntry, bool]:
    """Insert (idempotent) and move matching leads that aren't mid-call to status `dnc`.
    Returns (entry, created)."""
    existing = await session.scalar(
        select(DncEntry).where(
            DncEntry.phone_e164 == phone_e164,
            DncEntry.scope == scope,
            DncEntry.client_id.is_(None) if client_id is None else DncEntry.client_id == client_id,
        )
    )
    if existing:
        return existing, False
    entry = DncEntry(
        phone_e164=phone_e164,
        scope=scope,
        client_id=client_id,
        reason=reason,
        source=source,
        created_by=actor.id if actor else None,
    )
    session.add(entry)
    await session.flush()
    lead_filter = [Lead.phone_e164 == phone_e164, Lead.status != LeadStatus.calling]
    if scope == DncScope.client:
        lead_filter.append(
            Lead.campaign_id.in_(select(Campaign.id).where(Campaign.client_id == client_id))
        )
    await session.execute(
        update(Lead)
        .where(*lead_filter)
        .values(status=LeadStatus.dnc, next_attempt_at=None, last_disposition="dnc")
    )
    audit(session, actor, "dnc.add", "dnc_entry", entry.id, after=snapshot(entry))
    return entry, True


@router.post("", response_model=DncOut, status_code=201)
async def create_dnc(body: DncIn, session: DbSession, actor: AnyUser) -> DncEntry:
    try:
        phone = normalize_phone(body.phone, body.default_region)
    except InvalidPhoneError as exc:
        raise HTTPException(422, str(exc)) from exc
    if body.client_id and await session.get(Client, body.client_id) is None:
        raise HTTPException(422, "client not found")
    entry, _ = await add_dnc(
        session, phone, body.scope, body.client_id, body.reason, "manual", actor
    )
    await session.commit()
    await session.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=204)
async def delete_dnc(entry_id: uuid.UUID, session: DbSession, actor: Admin) -> None:
    entry = await session.get(DncEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dnc entry not found")
    audit(session, actor, "dnc.delete", "dnc_entry", entry.id, before=snapshot(entry))
    await session.delete(entry)
    await session.commit()


@router.post("/check", response_model=DncCheckOut)
async def check_dnc(body: DncCheckIn, session: DbSession, _: AnyUser) -> DncCheckOut:
    normalized: dict[str, str] = {}
    invalid: list[str] = []
    for raw in body.phones:
        try:
            normalized[raw] = normalize_phone(raw, body.default_region)
        except InvalidPhoneError:
            invalid.append(raw)
    blocked = await dnc_phones(session, normalized.values(), body.client_id)
    return DncCheckOut(
        results={raw: e164 in blocked for raw, e164 in normalized.items()}, invalid=invalid
    )
