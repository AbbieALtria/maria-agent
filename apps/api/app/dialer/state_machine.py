"""Lead status transitions (docs/outbound/03-CRM-DATA-MODEL.md §2 + Clarifications).

Pure functions: no DB access. Callers (scheduler, internal call API, watchdog, CRM actions) load
the lead + campaign, call `transition(...)`, and apply the returned `Transition`.

Attempt counting: `attempts` is incremented when a call outcome is recorded (not when the lead is
picked), except a voicemail when `campaign.voicemail_counts_as_attempt` is false.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.crm.enums import CallOutcome, LeadStatus

# Outcomes that mean "nobody useful picked up; try again later" (03 §2 lists
# no_answer/busy/voicemail/ivr; no_human, failed and hung_up_early are treated the same way).
RETRYABLE_OUTCOMES = frozenset(
    {
        CallOutcome.no_answer,
        CallOutcome.busy,
        CallOutcome.voicemail,
        CallOutcome.ivr,
        CallOutcome.no_human,
        CallOutcome.failed,
        CallOutcome.hung_up_early,
    }
)

# Statuses the scheduler may pick from (Clarification 1: queued/callback only once due).
PICKABLE = frozenset({LeadStatus.new, LeadStatus.queued, LeadStatus.callback})

# Conversation dispositions that map straight onto a lead status.
DISPOSITION_STATUS = {
    "appointment_set": LeadStatus.appointment_set,
    "callback": LeadStatus.callback,
    "not_interested": LeadStatus.not_interested,
    "wrong_number": LeadStatus.wrong_number,
    "dnc": LeadStatus.dnc,
}

# Never re-dial these via a manual requeue (DNC is a legal opt-out; `calling` would allow a
# concurrent second dial).
NOT_REQUEUEABLE = frozenset({LeadStatus.dnc, LeadStatus.calling})


class InvalidTransition(ValueError):
    pass


@dataclass(frozen=True)
class CampaignRules:
    max_attempts: int = 3
    retry_spacing_hours: int = 4
    voicemail_counts_as_attempt: bool = False
    requeue_no_show: bool = False


# --- events ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SchedulerPick:
    pass


@dataclass(frozen=True)
class CallFinished:
    outcome: CallOutcome
    disposition: str | None = None
    callback_at: datetime | None = None  # from schedule_callback tool


@dataclass(frozen=True)
class ManualRequeue:
    pass


@dataclass(frozen=True)
class AppointmentNoShow:
    pass


@dataclass(frozen=True)
class WatchdogStale:
    # How many earlier attempts of this lead already ended failed_stale. Only the first stale
    # attempt requeues; a repeat means something is systematically broken → exhausted.
    previous_stale_attempts: int = 0


Event = SchedulerPick | CallFinished | ManualRequeue | AppointmentNoShow | WatchdogStale


@dataclass(frozen=True)
class Transition:
    status: LeadStatus
    attempts: int
    next_attempt_at: datetime | None = None
    add_to_dnc: bool = False
    last_disposition: str | None = None


def transition(
    status: LeadStatus,
    attempts: int,
    event: Event,
    rules: CampaignRules,
    now: datetime,
) -> Transition | None:
    """Return the new lead state, None when the event leaves the lead unchanged, or raise
    InvalidTransition when the event is not allowed from `status`."""
    match event:
        case SchedulerPick():
            if status not in PICKABLE:
                raise InvalidTransition(f"scheduler cannot pick a lead in status {status}")
            return Transition(LeadStatus.calling, attempts)

        case CallFinished():
            if status != LeadStatus.calling:
                raise InvalidTransition(f"call finished for a lead in status {status}")
            return _call_finished(attempts, event, rules, now)

        case ManualRequeue():
            if status in NOT_REQUEUEABLE:
                raise InvalidTransition(f"cannot requeue a lead in status {status}")
            return Transition(LeadStatus.queued, attempts, next_attempt_at=None)

        case AppointmentNoShow():
            if status != LeadStatus.appointment_set:
                raise InvalidTransition(f"no-show for a lead in status {status}")
            if not rules.requeue_no_show:
                return None
            return Transition(LeadStatus.callback, attempts, next_attempt_at=now)

        case WatchdogStale():
            if status != LeadStatus.calling:
                return None  # the call already finished and moved the lead on
            if event.previous_stale_attempts > 0:
                return Transition(LeadStatus.exhausted, attempts, last_disposition="failed_stale")
            return Transition(
                LeadStatus.queued, attempts, next_attempt_at=now, last_disposition="failed_stale"
            )

    raise InvalidTransition(f"unknown event {event!r}")


def _call_finished(
    attempts: int, event: CallFinished, rules: CampaignRules, now: datetime
) -> Transition:
    counts = not (event.outcome == CallOutcome.voicemail and not rules.voicemail_counts_as_attempt)
    attempts = attempts + 1 if counts else attempts
    disposition = event.disposition or event.outcome.value

    if event.outcome == CallOutcome.invalid_number:
        return Transition(LeadStatus.invalid, attempts, last_disposition=disposition)

    if event.outcome in RETRYABLE_OUTCOMES:
        if attempts >= rules.max_attempts:
            return Transition(LeadStatus.exhausted, attempts, last_disposition=disposition)
        return Transition(
            LeadStatus.queued,
            attempts,
            next_attempt_at=now + timedelta(hours=rules.retry_spacing_hours),
            last_disposition=disposition,
        )

    # outcome == conversation
    target = DISPOSITION_STATUS.get(event.disposition or "")
    if target == LeadStatus.callback:
        return Transition(
            LeadStatus.callback,
            attempts,
            next_attempt_at=event.callback_at or now + timedelta(hours=rules.retry_spacing_hours),
            last_disposition=disposition,
        )
    if target == LeadStatus.dnc:
        return Transition(LeadStatus.dnc, attempts, add_to_dnc=True, last_disposition=disposition)
    if target is not None:
        return Transition(target, attempts, last_disposition=disposition)
    # A conversation that ended without a terminal disposition (FR-L4 `contacted`).
    return Transition(LeadStatus.contacted, attempts, last_disposition=disposition)
