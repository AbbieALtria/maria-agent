import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.crm.audit import audit, snapshot
from app.crm.deps import Admin, DbSession, Manager
from app.crm.enums import Market
from app.crm.models import SipTrunk
from app.crm.schemas import SipTrunkIn, SipTrunkOut, SipTrunkUpdate
from maria_shared.phone import InvalidPhoneError, normalize_phone

router = APIRouter(prefix="/sip-trunks", tags=["sip_trunks"])


def _caller_ids(raw: list[str], market: Market) -> list[str]:
    region = None if market == Market.OTHER else market.value
    out: list[str] = []
    for n in raw:
        try:
            e164 = normalize_phone(n, region)
        except InvalidPhoneError as exc:
            raise HTTPException(422, f"caller id {n!r}: {exc}") from exc
        if e164 not in out:
            out.append(e164)
    return out


@router.get("", response_model=list[SipTrunkOut])
async def list_trunks(session: DbSession, _: Manager) -> list[SipTrunk]:
    return list(await session.scalars(select(SipTrunk).order_by(SipTrunk.name)))


@router.post("", response_model=SipTrunkOut, status_code=201)
async def create_trunk(body: SipTrunkIn, session: DbSession, actor: Admin) -> SipTrunk:
    data = body.model_dump()
    data["caller_ids"] = _caller_ids(body.caller_ids, body.market)
    trunk = SipTrunk(**data)
    session.add(trunk)
    await session.flush()
    audit(session, actor, "sip_trunk.create", "sip_trunk", trunk.id, after=snapshot(trunk))
    await session.commit()
    await session.refresh(trunk)
    return trunk


@router.patch("/{trunk_id}", response_model=SipTrunkOut)
async def update_trunk(
    trunk_id: uuid.UUID, body: SipTrunkUpdate, session: DbSession, actor: Admin
) -> SipTrunk:
    trunk = await session.get(SipTrunk, trunk_id)
    if trunk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sip trunk not found")
    before = snapshot(trunk)
    changes = body.model_dump(exclude_unset=True)
    market = changes.get("market") or trunk.market
    if changes.get("caller_ids") is not None:
        changes["caller_ids"] = _caller_ids(changes["caller_ids"], market)
    for k, v in changes.items():
        if v is not None or k in ("livekit_trunk_id", "provider"):
            setattr(trunk, k, v)
    audit(session, actor, "sip_trunk.update", "sip_trunk", trunk.id, before, snapshot(trunk))
    await session.commit()
    await session.refresh(trunk)
    return trunk
