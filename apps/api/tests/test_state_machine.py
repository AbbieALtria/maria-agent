from datetime import UTC, datetime, timedelta

import pytest

from app.crm.enums import CallOutcome, LeadStatus
from app.dialer.state_machine import (
    AppointmentNoShow,
    CallFinished,
    CampaignRules,
    InvalidTransition,
    ManualRequeue,
    SchedulerPick,
    WatchdogStale,
    transition,
)

NOW = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)
RULES = CampaignRules(max_attempts=3, retry_spacing_hours=4)


@pytest.mark.parametrize("status", [LeadStatus.new, LeadStatus.queued, LeadStatus.callback])
def test_scheduler_picks(status: LeadStatus) -> None:
    t = transition(status, 1, SchedulerPick(), RULES, NOW)
    assert t is not None and t.status == LeadStatus.calling and t.attempts == 1


@pytest.mark.parametrize(
    "status", [LeadStatus.calling, LeadStatus.dnc, LeadStatus.appointment_set, LeadStatus.invalid]
)
def test_scheduler_cannot_pick(status: LeadStatus) -> None:
    with pytest.raises(InvalidTransition):
        transition(status, 0, SchedulerPick(), RULES, NOW)


@pytest.mark.parametrize(
    "outcome", [CallOutcome.no_answer, CallOutcome.busy, CallOutcome.ivr, CallOutcome.no_human]
)
def test_retryable_under_max_requeues_with_spacing(outcome: CallOutcome) -> None:
    t = transition(LeadStatus.calling, 0, CallFinished(outcome), RULES, NOW)
    assert t is not None
    assert t.status == LeadStatus.queued
    assert t.attempts == 1
    assert t.next_attempt_at == NOW + timedelta(hours=4)
    assert t.last_disposition == outcome.value


def test_retryable_at_max_exhausts() -> None:
    t = transition(LeadStatus.calling, 2, CallFinished(CallOutcome.busy), RULES, NOW)
    assert t is not None and t.status == LeadStatus.exhausted and t.attempts == 3


def test_voicemail_not_counted_by_default() -> None:
    t = transition(LeadStatus.calling, 2, CallFinished(CallOutcome.voicemail), RULES, NOW)
    assert t is not None and t.status == LeadStatus.queued and t.attempts == 2


def test_voicemail_counted_when_configured() -> None:
    rules = CampaignRules(max_attempts=3, voicemail_counts_as_attempt=True)
    t = transition(LeadStatus.calling, 2, CallFinished(CallOutcome.voicemail), rules, NOW)
    assert t is not None and t.status == LeadStatus.exhausted and t.attempts == 3


@pytest.mark.parametrize(
    ("disposition", "expected"),
    [
        ("appointment_set", LeadStatus.appointment_set),
        ("not_interested", LeadStatus.not_interested),
        ("wrong_number", LeadStatus.wrong_number),
        ("something_else", LeadStatus.contacted),
        (None, LeadStatus.contacted),
    ],
)
def test_conversation_dispositions(disposition: str | None, expected: LeadStatus) -> None:
    t = transition(
        LeadStatus.calling, 0, CallFinished(CallOutcome.conversation, disposition), RULES, NOW
    )
    assert t is not None and t.status == expected and not t.add_to_dnc


def test_callback_uses_tool_time() -> None:
    when = NOW + timedelta(days=1)
    t = transition(
        LeadStatus.calling,
        0,
        CallFinished(CallOutcome.conversation, "callback", callback_at=when),
        RULES,
        NOW,
    )
    assert t is not None and t.status == LeadStatus.callback and t.next_attempt_at == when


def test_dnc_disposition_flags_dnc_insert() -> None:
    t = transition(LeadStatus.calling, 0, CallFinished(CallOutcome.conversation, "dnc"), RULES, NOW)
    assert t is not None and t.status == LeadStatus.dnc and t.add_to_dnc


def test_invalid_number() -> None:
    t = transition(LeadStatus.calling, 0, CallFinished(CallOutcome.invalid_number), RULES, NOW)
    assert t is not None and t.status == LeadStatus.invalid


def test_call_finished_requires_calling() -> None:
    with pytest.raises(InvalidTransition):
        transition(LeadStatus.queued, 0, CallFinished(CallOutcome.busy), RULES, NOW)


@pytest.mark.parametrize(
    "status",
    [LeadStatus.new, LeadStatus.exhausted, LeadStatus.not_interested, LeadStatus.appointment_set],
)
def test_manual_requeue(status: LeadStatus) -> None:
    t = transition(status, 3, ManualRequeue(), RULES, NOW)
    assert t is not None and t.status == LeadStatus.queued and t.next_attempt_at is None


@pytest.mark.parametrize("status", [LeadStatus.dnc, LeadStatus.calling])
def test_manual_requeue_blocked(status: LeadStatus) -> None:
    with pytest.raises(InvalidTransition):
        transition(status, 0, ManualRequeue(), RULES, NOW)


def test_no_show_requeue_depends_on_campaign() -> None:
    assert transition(LeadStatus.appointment_set, 1, AppointmentNoShow(), RULES, NOW) is None
    rules = CampaignRules(requeue_no_show=True)
    t = transition(LeadStatus.appointment_set, 1, AppointmentNoShow(), rules, NOW)
    assert t is not None and t.status == LeadStatus.callback and t.next_attempt_at == NOW


def test_watchdog_requeues_once() -> None:
    t = transition(LeadStatus.calling, 1, WatchdogStale(), RULES, NOW)
    assert t is not None and t.status == LeadStatus.queued and t.next_attempt_at == NOW
    t = transition(LeadStatus.calling, 1, WatchdogStale(previous_stale_attempts=1), RULES, NOW)
    assert t is not None and t.status == LeadStatus.exhausted


def test_watchdog_ignores_leads_no_longer_calling() -> None:
    assert transition(LeadStatus.queued, 1, WatchdogStale(), RULES, NOW) is None
