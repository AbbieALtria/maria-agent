"""Test calls (Phase 2) and call read endpoints."""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import func, select

from app.crm.audit import audit
from app.crm.deps import AnyUser, DbSession, Manager
from app.crm.enums import AttemptStatus, CallOutcome, LeadStatus
from app.crm.models import Appointment, CallAttempt, CallEvent, Campaign, Lead, SipTrunk
from app.crm.services.dnc import dnc_phones
from app.dialer.calls import (
    ACTIVE_STATUSES,
    blocked_by_test_mode,
    campaign_rules,
    now_utc,
    playbook_for,
)
from app.dialer.livekit_client import Dispatcher, get_dispatcher
from app.dialer.state_machine import (
    PICKABLE,
    InvalidTransition,
    ManualRequeue,
    SchedulerPick,
    transition,
)
from app.logging import log_context

log = logging.getLogger("maria.calls")

router = APIRouter(tags=["calls"])


class TestCallIn(BaseModel):
    lead_id: uuid.UUID


class TestCallOut(BaseModel):
    attempt_id: uuid.UUID
    lead_id: uuid.UUID
    room: str
    dispatch_id: str


def _refuse(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, f"test call refused: {msg}")


@router.post("/campaigns/{campaign_id}/test-call", response_model=TestCallOut)
async def test_call(
    campaign_id: uuid.UUID,
    body: TestCallIn,
    session: DbSession,
    user: Manager,
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
) -> TestCallOut:
    """Dial one lead now. Only for campaigns in test mode and numbers on the test allowlist."""
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "campaign not found")
    # Row lock: two concurrent test calls for one lead serialize here; the second sees `calling`.
    lead = await session.scalar(
        select(Lead)
        .where(Lead.id == body.lead_id, Lead.campaign_id == campaign.id)
        .with_for_update()
    )
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "lead not found in this campaign")

    with log_context(campaign_id=str(campaign.id)):
        if not campaign.test_mode:
            raise _refuse("campaign is not in test mode")
        if blocked_by_test_mode(campaign, lead.phone_e164):
            raise _refuse("lead phone is not in the campaign's test allowlist")
        if await dnc_phones(session, [lead.phone_e164], campaign.client_id):
            raise _refuse("lead phone is on the DNC list")
        if lead.status in (LeadStatus.calling, LeadStatus.dnc):
            raise _refuse(f"lead is {lead.status.value}")
        active = await session.scalar(
            select(func.count())
            .select_from(CallAttempt)
            .where(CallAttempt.lead_id == lead.id, CallAttempt.status.in_(ACTIVE_STATUSES))
        )
        if active:
            raise _refuse("lead already has a call in progress")
        trunk = (
            await session.get(SipTrunk, campaign.sip_trunk_id) if campaign.sip_trunk_id else None
        )
        if trunk is None or not trunk.livekit_trunk_id or not trunk.is_active:
            raise _refuse("campaign needs an active SIP trunk with a LiveKit trunk id")
        if not campaign.caller_id:
            raise _refuse("campaign has no caller_id")
        pv, playbook, errors = await playbook_for(session, campaign.active_playbook_version_id)
        if playbook is None or pv is None:
            raise _refuse("no valid active playbook: " + "; ".join(errors))

        # A test call is a manual requeue followed by an immediate pick.
        rules, now = campaign_rules(campaign), now_utc()
        try:
            if lead.status not in PICKABLE:
                t = transition(lead.status, lead.attempts, ManualRequeue(), rules, now)
                assert t is not None
                lead.status, lead.next_attempt_at = t.status, t.next_attempt_at
            t = transition(lead.status, lead.attempts, SchedulerPick(), rules, now)
        except InvalidTransition as exc:
            raise _refuse(str(exc)) from exc
        assert t is not None
        lead.status = t.status

        attempt_id = uuid.uuid4()
        attempt_no = (
            await session.scalar(
                select(func.count()).select_from(CallAttempt).where(CallAttempt.lead_id == lead.id)
            )
            or 0
        ) + 1
        room = f"call-{attempt_id}"
        attempt = CallAttempt(
            id=attempt_id,
            lead_id=lead.id,
            campaign_id=campaign.id,
            playbook_version_id=pv.id,
            attempt_no=attempt_no,
            status=AttemptStatus.dialing,
            livekit_room=room,
        )
        session.add(attempt)
        audit(
            session, user, "call.test_call", "call_attempt", attempt_id,
            after={"lead_id": str(lead.id), "phone": lead.phone_e164},
        )  # fmt: skip
        await session.commit()

        metadata = {
            "attempt_id": str(attempt_id),
            "campaign_id": str(campaign.id),
            "lead_id": str(lead.id),
            "phone": lead.phone_e164,
            "trunk_id": trunk.livekit_trunk_id,
            "caller_id": campaign.caller_id,
            "playbook_version_id": str(pv.id),
            "test": True,
        }
        with log_context(attempt_id=str(attempt_id)):
            try:
                dispatch_id = await dispatcher.dispatch(room, metadata)
            except Exception as exc:
                log.exception("agent dispatch failed")
                attempt.status = AttemptStatus.failed
                attempt.outcome = CallOutcome.failed
                attempt.sip_error = f"dispatch failed: {type(exc).__name__}"
                attempt.end_reason = "dispatch_failed"
                # Nothing was dialed: put the lead back without counting an attempt.
                lead.status = LeadStatus.queued
                await session.commit()
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY, "LiveKit agent dispatch failed"
                ) from exc
            log.info("test call dispatched", extra={"room": room})
    return TestCallOut(attempt_id=attempt_id, lead_id=lead.id, room=room, dispatch_id=dispatch_id)


@router.get("/calls/{attempt_id}")
async def read_call(attempt_id: uuid.UUID, session: DbSession, _: AnyUser) -> dict[str, Any]:
    """Attempt with transcript, result, tool/stage events and the booked appointment."""
    attempt = await session.get(CallAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    lead = await session.get(Lead, attempt.lead_id)
    events = await session.scalars(
        select(CallEvent)
        .where(CallEvent.call_attempt_id == attempt.id)
        .order_by(CallEvent.ts, CallEvent.created_at)
    )
    appt = (
        await session.get(Appointment, attempt.appointment_id) if attempt.appointment_id else None
    )
    data = {c.key: getattr(attempt, c.key) for c in CallAttempt.__table__.columns}
    data["lead"] = {
        "id": lead.id,
        "status": lead.status,
        "business_name": lead.business_name,
        "contact_name": lead.contact_name,
        "attempts": lead.attempts,
        "next_attempt_at": lead.next_attempt_at,
        "last_disposition": lead.last_disposition,
    } if lead else None  # fmt: skip
    data["events"] = [{"ts": e.ts, "type": e.type, "payload": e.payload} for e in events]
    data["appointment"] = (
        {
            "id": appt.id,
            "start_at": appt.start_at,
            "end_at": appt.end_at,
            "prospect_timezone": appt.prospect_timezone,
            "type": appt.type,
            "status": appt.status,
        }
        if appt
        else None
    )
    return jsonable_encoder(data)
