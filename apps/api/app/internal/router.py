"""Internal API used only by the voice-worker (header X-Internal-Secret).

docs/outbound/03-CRM-DATA-MODEL.md §3 "Internal" and §4.
"""

import logging
import uuid
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import cast

from app.crm.deps import DbSession
from app.crm.enums import AttemptStatus, CallOutcome
from app.crm.models import CallAttempt, CallEvent, Campaign, Lead, SipTrunk
from app.dialer.calls import (
    FINAL_STATUSES,
    apply_call_finished,
    blocked_by_test_mode,
    lead_timezone,
    now_utc,
    playbook_for,
    set_disposition,
)
from app.dialer.slots import offer_slots
from app.internal.deps import InternalAuth
from app.internal.schemas import CallEventIn, CallPatch
from app.internal.tools import TOOLS, ToolArgsError, ToolCtx
from app.logging import log_context

log = logging.getLogger("maria.internal")

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[InternalAuth])

LEAD_FIELDS = (
    "id", "business_name", "contact_name", "contact_title", "phone_e164", "email",
    "address_line", "city", "region", "postal_code", "country_code", "timezone", "website",
    "industry", "custom", "notes",
)  # fmt: skip


async def _attempt(session: DbSession, attempt_id: uuid.UUID, lock: bool = False) -> CallAttempt:
    stmt = select(CallAttempt).where(CallAttempt.id == attempt_id)
    attempt = await session.scalar(stmt.with_for_update() if lock else stmt)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call attempt not found")
    return attempt


@router.get("/dispatch-context/{attempt_id}")
async def dispatch_context(attempt_id: uuid.UUID, session: DbSession) -> dict[str, Any]:
    attempt = await _attempt(session, attempt_id)
    lead = await session.get(Lead, attempt.lead_id)
    campaign = await session.get(Campaign, attempt.campaign_id)
    assert lead is not None and campaign is not None
    with log_context(attempt_id=str(attempt.id), campaign_id=str(campaign.id)):
        if attempt.status in FINAL_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, "attempt already finished")
        # Second line of defence behind the test-call endpoint / scheduler.
        if blocked_by_test_mode(campaign, lead.phone_e164):
            log.warning("dispatch refused: phone not in test allowlist")
            raise HTTPException(status.HTTP_409_CONFLICT, "phone not in test allowlist")
        pv, playbook, errors = await playbook_for(session, attempt.playbook_version_id)
        if playbook is None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"invalid playbook: {errors}")
        trunk = (
            await session.get(SipTrunk, campaign.sip_trunk_id) if campaign.sip_trunk_id else None
        )
        tz = lead_timezone(lead, campaign)
        now = now_utc()
        a = playbook.goal.appointment
        slots, _ = offer_slots(
            now, tz, min_lead_time_hours=a.min_lead_time_hours, max_days_ahead=a.max_days_ahead
        )
        return jsonable_encoder(
            {
                "attempt": {
                    "id": attempt.id,
                    "attempt_no": attempt.attempt_no,
                    "status": attempt.status,
                    "livekit_room": attempt.livekit_room,
                },
                "campaign": {
                    "id": campaign.id,
                    "name": campaign.name,
                    "client_id": campaign.client_id,
                    "test_mode": campaign.test_mode,
                },
                "lead": {f: getattr(lead, f) for f in LEAD_FIELDS},
                "playbook_version_id": pv.id if pv else None,
                "playbook": pv.playbook if pv else None,
                "prospect_timezone": tz,
                "now_local": now.astimezone(ZoneInfo(tz)),
                "slots": [s.as_dict() for s in slots[: a.offer_slots_count * 2]],
                "phone": lead.phone_e164,
                "trunk_id": trunk.livekit_trunk_id if trunk else None,
                "caller_id": campaign.caller_id,
            }
        )


@router.patch("/calls/{attempt_id}")
async def patch_call(attempt_id: uuid.UUID, body: CallPatch, session: DbSession) -> dict[str, Any]:
    attempt = await _attempt(session, attempt_id, lock=True)
    with log_context(attempt_id=str(attempt.id), campaign_id=str(attempt.campaign_id)):
        changes = body.model_dump(exclude_unset=True)
        finishing = "outcome" in changes and attempt.outcome is None
        disposition = changes.pop("disposition", None)
        for key, value in changes.items():
            if key == "outcome" and attempt.outcome is not None:
                continue  # the first final outcome wins
            setattr(attempt, key, value)
        set_disposition(attempt, disposition)
        if attempt.duration_sec is None and attempt.started_at and attempt.ended_at:
            attempt.duration_sec = int((attempt.ended_at - attempt.started_at).total_seconds())

        state: dict[str, Any] = {"applied": False}
        if finishing:
            if "status" not in changes:
                failed = changes["outcome"] == CallOutcome.failed
                attempt.status = AttemptStatus.failed if failed else AttemptStatus.completed
            attempt.ended_at = attempt.ended_at or now_utc()
            state = await apply_call_finished(session, attempt)
            log.info(
                "call finished",
                extra={
                    "outcome": attempt.outcome,
                    "disposition": attempt.disposition,
                    "lead_status": state.get("lead_status"),
                },
            )
        await session.commit()
        return jsonable_encoder(
            {
                "id": attempt.id,
                "status": attempt.status,
                "outcome": attempt.outcome,
                "disposition": attempt.disposition,
                "lead_state": state,
            }
        )


@router.post("/calls/{attempt_id}/events", status_code=201)
async def post_event(attempt_id: uuid.UUID, body: CallEventIn, session: DbSession) -> dict:
    attempt = await _attempt(session, attempt_id)
    ts = body.ts or now_utc()
    if body.type == "turn":
        if body.role is None or body.text is None:
            raise HTTPException(422, "a turn needs role and text")
        item = {"role": body.role, "text": body.text, "ts": ts, "latency_ms": body.latency_ms}
        # Atomic append so concurrent events never lose a turn.
        await session.execute(
            update(CallAttempt)
            .where(CallAttempt.id == attempt.id)
            .values(
                transcript=CallAttempt.transcript.op("||")(cast([jsonable_encoder(item)], JSONB))
            )
        )
    else:
        session.add(
            CallEvent(call_attempt_id=attempt.id, ts=ts, type=body.type, payload=body.payload)
        )
    await session.commit()
    return {"ok": True}


@router.post("/calls/{attempt_id}/tool/{name}")
async def run_tool(
    attempt_id: uuid.UUID,
    name: str,
    session: DbSession,
    args: Annotated[dict[str, Any], Body()] = {},  # noqa: B006 (FastAPI copies defaults)
) -> dict[str, Any]:
    fn = TOOLS.get(name)
    if fn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown tool {name}")
    attempt = await _attempt(session, attempt_id, lock=True)
    lead = await session.get(Lead, attempt.lead_id)
    campaign = await session.get(Campaign, attempt.campaign_id)
    assert lead is not None and campaign is not None
    with log_context(attempt_id=str(attempt.id), campaign_id=str(campaign.id)):
        _, playbook, errors = await playbook_for(session, attempt.playbook_version_id)
        if playbook is None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"invalid playbook: {errors}")
        ctx = ToolCtx(session, attempt, lead, campaign, playbook, now_utc())
        try:
            result = await fn(ctx, args)
        except ToolArgsError as exc:
            result = {"ok": False, "error": f"invalid arguments: {exc}"}
        session.add(
            CallEvent(
                call_attempt_id=attempt.id,
                ts=ctx.now,
                type="tool",
                payload=jsonable_encoder({"name": name, "args": args, "result": result}),
            )
        )
        await session.commit()
        log.info("tool", extra={"tool": name, "ok": result.get("ok", result.get("allowed"))})
        return result
