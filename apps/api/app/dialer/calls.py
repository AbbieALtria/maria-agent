"""Call-attempt helpers shared by the test-call endpoint, the internal (voice-worker) API and,
from Phase 3, the scheduler."""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.enums import AttemptStatus, CallOutcome, DncScope, LeadStatus
from app.crm.models import CallAttempt, CallEvent, Campaign, Lead, PlaybookVersion
from app.dialer.state_machine import CallFinished, CampaignRules, transition
from playbook_schema import Playbook

log = logging.getLogger("maria.dialer.calls")

# Higher wins when tools, end_call and the post-call analysis disagree. An opt-out always wins;
# a booked appointment beats anything the analysis model infers afterwards.
DISPOSITION_PRIORITY = {
    "dnc": 100,
    "appointment_set": 90,
    "wrong_number": 80,
    "callback": 70,
    "not_interested": 60,
}
FINAL_STATUSES = frozenset(
    {AttemptStatus.completed, AttemptStatus.failed, AttemptStatus.failed_stale}
)
ACTIVE_STATUSES = frozenset({AttemptStatus.dialing, AttemptStatus.ringing, AttemptStatus.in_call})


def now_utc() -> datetime:
    return datetime.now(UTC)


def set_disposition(attempt: CallAttempt, disposition: str | None) -> None:
    if not disposition:
        return
    current = attempt.disposition
    if current is None or DISPOSITION_PRIORITY.get(disposition, 10) >= DISPOSITION_PRIORITY.get(
        current, 10
    ):
        attempt.disposition = disposition


def lead_timezone(lead: Lead, campaign: Campaign) -> str:
    return lead.timezone or campaign.default_timezone


def campaign_rules(campaign: Campaign) -> CampaignRules:
    return CampaignRules(
        max_attempts=campaign.max_attempts,
        retry_spacing_hours=campaign.retry_spacing_hours,
        voicemail_counts_as_attempt=campaign.voicemail_counts_as_attempt,
        requeue_no_show=campaign.requeue_no_show,
    )


def blocked_by_test_mode(campaign: Campaign, phone_e164: str) -> bool:
    """CLAUDE.md: while test_mode is on, only numbers in test_allowlist may be dialed."""
    return campaign.test_mode and phone_e164 not in (campaign.test_allowlist or [])


async def playbook_for(
    session: AsyncSession, version_id: Any
) -> tuple[PlaybookVersion | None, Playbook | None, list[str]]:
    """(version row, parsed playbook, validation errors)."""
    from playbook_schema import validation_errors

    pv = await session.get(PlaybookVersion, version_id) if version_id else None
    if pv is None:
        return None, None, ["no playbook version"]
    errors = validation_errors(pv.playbook)
    return pv, (None if errors else Playbook.model_validate(pv.playbook)), errors


async def callback_at(session: AsyncSession, attempt_id: Any) -> datetime | None:
    """`callback_at` recorded by the latest schedule_callback tool call of this attempt."""
    payload = await session.scalar(
        select(CallEvent.payload)
        .where(
            CallEvent.call_attempt_id == attempt_id,
            CallEvent.type == "tool",
            CallEvent.payload["name"].astext == "schedule_callback",
        )
        .order_by(CallEvent.ts.desc(), CallEvent.created_at.desc())
        .limit(1)
    )
    iso = ((payload or {}).get("result") or {}).get("callback_at")
    return datetime.fromisoformat(iso) if iso else None


async def apply_call_finished(session: AsyncSession, attempt: CallAttempt) -> dict[str, Any]:
    """Apply the lead state machine (03 §2) for a finished attempt. Call once per attempt."""
    from app.crm.routers.dnc import add_dnc  # avoid an import cycle with the CRM routers

    lead = await session.scalar(select(Lead).where(Lead.id == attempt.lead_id).with_for_update())
    campaign = await session.get(Campaign, attempt.campaign_id)
    assert lead is not None and campaign is not None
    if lead.status != LeadStatus.calling:
        # The watchdog (or a manual action) already moved the lead on.
        log.warning("lead not in calling; state unchanged", extra={"lead_status": lead.status})
        return {"applied": False, "lead_status": lead.status.value}

    outcome = attempt.outcome or CallOutcome.failed
    if attempt.appointment_id is not None:
        attempt.disposition = "appointment_set"
        outcome = CallOutcome.conversation
    disposition = attempt.disposition if outcome == CallOutcome.conversation else None
    cb = await callback_at(session, attempt.id) if disposition == "callback" else None
    now = now_utc()
    t = transition(
        lead.status,
        lead.attempts,
        CallFinished(outcome=outcome, disposition=disposition, callback_at=cb),
        campaign_rules(campaign),
        now,
    )
    assert t is not None
    lead.status = t.status
    lead.attempts = t.attempts
    lead.next_attempt_at = t.next_attempt_at
    lead.last_attempt_at = attempt.started_at or now
    lead.last_disposition = t.last_disposition
    if t.add_to_dnc:
        await add_dnc(
            session, lead.phone_e164, DncScope.global_, None, "opted out on call", "call", None
        )
    return {"applied": True, "lead_status": t.status.value, "attempts": t.attempts}
