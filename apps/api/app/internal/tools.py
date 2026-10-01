"""Call tools executed for the voice-worker (docs/outbound/03-CRM-DATA-MODEL.md §4).

Every tool is idempotent per attempt. Tools record dispositions on the attempt; the lead's status
changes once, when the worker PATCHes the final outcome (app/dialer/calls.apply_call_finished).
add_to_dnc is the exception that acts immediately: the DNC entry is written at once.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.audit import audit, snapshot
from app.crm.enums import AppointmentType, ConsentType, DncScope
from app.crm.models import (
    Appointment,
    AppointmentEvent,
    CallAttempt,
    Campaign,
    ConsentEvent,
    Lead,
)
from app.dialer.calls import lead_timezone, set_disposition
from app.dialer.slots import human_time, match_slot, offer_slots, parse_callback_time
from playbook_schema import STAGES, Playbook

log = logging.getLogger("maria.internal.tools")


@dataclass
class ToolCtx:
    session: AsyncSession
    attempt: CallAttempt
    lead: Lead
    campaign: Campaign
    playbook: Playbook
    now: datetime

    @property
    def tz(self) -> str:
        return lead_timezone(self.lead, self.campaign)


class _Args(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CheckSlotsArgs(_Args):
    preferred_day: str | None = None
    preferred_part_of_day: str | None = None
    count: int | None = Field(default=None, ge=1, le=4)


class BookArgs(_Args):
    slot_start_iso: str
    type: AppointmentType | None = None
    contact_name: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None


class CallbackArgs(_Args):
    when_iso: str | None = None
    relative_text: str | None = None
    reason: str | None = None


class ReasonArgs(_Args):
    reason: str | None = None


class NoteArgs(_Args):
    note: str | None = None


class StageArgs(_Args):
    stage: Literal[STAGES]  # type: ignore[valid-type]


class EndCallArgs(_Args):
    disposition: str | None = None
    farewell_said: bool = True


class ToolArgsError(ValueError):
    pass


def _parse(model: type[_Args], args: dict[str, Any]) -> Any:
    try:
        return model.model_validate(args)
    except ValidationError as exc:
        raise ToolArgsError(
            "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        ) from exc


def _slot_window(ctx: ToolCtx) -> dict[str, int]:
    a = ctx.playbook.goal.appointment
    return {"min_lead_time_hours": a.min_lead_time_hours, "max_days_ahead": a.max_days_ahead}


async def check_slots(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    a = _parse(CheckSlotsArgs, args)
    slots, note = offer_slots(
        ctx.now,
        ctx.tz,
        preferred_day=a.preferred_day,
        preferred_part_of_day=a.preferred_part_of_day,
        count=a.count,
        **_slot_window(ctx),
    )
    return {"slots": [s.as_dict() for s in slots], "timezone": ctx.tz, "note": note}


async def book_appointment(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    a = _parse(BookArgs, args)
    s = ctx.session
    if ctx.attempt.appointment_id is not None:
        existing = await s.get(Appointment, ctx.attempt.appointment_id)
        assert existing is not None
        return {
            "ok": True,
            "already_booked": True,
            "appointment_id": str(existing.id),
            "confirmation": human_time(existing.start_at.astimezone(_zone(ctx))),
        }
    goal = ctx.playbook.goal.appointment
    slot = match_slot(a.slot_start_iso, ctx.now, ctx.tz, **_slot_window(ctx))
    if slot is None:
        slots, _ = offer_slots(ctx.now, ctx.tz, **_slot_window(ctx))
        return {
            "ok": False,
            "error": "that time is not an available slot; offer one of these instead",
            "slots": [x.as_dict() for x in slots],
        }
    if goal.require_address and not (a.address or ctx.lead.address_line):
        return {"ok": False, "error": "an address is required; ask for it, then book again"}

    appt_type = a.type or AppointmentType(goal.type)
    settings = ctx.campaign.appointment_settings or {}
    appt = Appointment(
        lead_id=ctx.lead.id,
        campaign_id=ctx.campaign.id,
        call_attempt_id=ctx.attempt.id,
        team_id=settings.get("team_id"),
        type=appt_type,
        start_at=slot.start,
        end_at=slot.start + timedelta(minutes=goal.duration_min),
        prospect_timezone=ctx.tz,
        location_address=a.address or (ctx.lead.address_line if appt_type == "onsite" else None),
        notes=a.notes,
    )
    s.add(appt)
    await s.flush()
    s.add(
        AppointmentEvent(
            appointment_id=appt.id,
            type="created",
            payload={"source": "maria", "call_attempt_id": str(ctx.attempt.id)},
        )
    )
    if a.email and a.email.strip():
        ctx.lead.email = a.email.strip().lower()
    if a.contact_name and not ctx.lead.contact_name:
        ctx.lead.contact_name = a.contact_name.strip()
    ctx.attempt.appointment_id = appt.id
    set_disposition(ctx.attempt, "appointment_set")
    audit(s, None, "appointment.create", "appointment", appt.id, after=snapshot(appt))
    missing = [
        f
        for f, needed, have in (
            ("email", goal.require_email, ctx.lead.email),
            ("address", goal.require_address, appt.location_address),
        )
        if needed and not have
    ]
    # Confirmation SMS/email arrive with notifications in Phase 4.
    return {
        "ok": True,
        "appointment_id": str(appt.id),
        "start_iso": slot.start.isoformat(),
        "confirmation": slot.label,
        "missing": missing,
    }


def _zone(ctx: ToolCtx):
    from zoneinfo import ZoneInfo

    return ZoneInfo(ctx.tz)


async def schedule_callback(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    a = _parse(CallbackArgs, args)
    when, understood = parse_callback_time(
        ctx.now, ctx.tz, when_iso=a.when_iso, relative_text=a.relative_text
    )
    set_disposition(ctx.attempt, "callback")
    return {
        "ok": True,
        "callback_at": when.isoformat(),
        "callback_human": human_time(when),
        "understood": understood,
    }


async def mark_not_interested(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    _parse(ReasonArgs, args)
    set_disposition(ctx.attempt, "not_interested")
    return {"ok": True}


async def mark_wrong_number(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    _parse(NoteArgs, args)
    set_disposition(ctx.attempt, "wrong_number")
    return {"ok": True}


async def add_to_dnc(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    from app.crm.routers.dnc import add_dnc

    a = _parse(ReasonArgs, args)
    _, created = await add_dnc(
        ctx.session,
        ctx.lead.phone_e164,
        DncScope.global_,
        None,
        a.reason or "opted out on call",
        "call",
        None,
    )
    if created:
        ctx.session.add(
            ConsentEvent(
                lead_id=ctx.lead.id, call_attempt_id=ctx.attempt.id, type=ConsentType.opt_out
            )
        )
    set_disposition(ctx.attempt, "dnc")
    return {"ok": True}


async def set_stage(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    a = _parse(StageArgs, args)
    current = ctx.attempt.stage_reached
    if current not in STAGES or STAGES.index(a.stage) > STAGES.index(current):
        ctx.attempt.stage_reached = a.stage
    return {"ok": True, "stage": a.stage}


async def end_call(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    a = _parse(EndCallArgs, args)
    set_disposition(ctx.attempt, a.disposition)
    ctx.attempt.end_reason = "end_call"
    return {"ok": True}


async def not_available(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    return {"allowed": False, "reason": "not available yet; offer a follow-up from the team"}


async def escalate_complaint(ctx: ToolCtx, args: dict[str, Any]) -> dict[str, Any]:
    ctx.attempt.needs_review = True
    ctx.attempt.review_reason = "complaint escalated on call"
    return {"allowed": False, "reason": "logged for review; a manager will follow up"}


TOOLS: dict[str, Callable[[ToolCtx, dict[str, Any]], Awaitable[dict[str, Any]]]] = {
    "check_slots": check_slots,
    "book_appointment": book_appointment,
    "schedule_callback": schedule_callback,
    "mark_not_interested": mark_not_interested,
    "mark_wrong_number": mark_wrong_number,
    "add_to_dnc": add_to_dnc,
    "send_info": not_available,
    "transfer_to_human": not_available,
    "escalate_complaint": escalate_complaint,
    "set_stage": set_stage,
    "end_call": end_call,
}
