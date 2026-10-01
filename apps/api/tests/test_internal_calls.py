"""Internal (voice-worker) API: auth, dispatch context, tools, events and result application."""

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from tests.conftest import PHONE

from app.config import get_settings
from app.crm.enums import AttemptStatus, LeadStatus
from app.crm.models import (
    Appointment,
    CallEvent,
    ConsentEvent,
    DncEntry,
)


def internal_headers() -> dict[str, str]:
    return {"X-Internal-Secret": get_settings().internal_api_secret.get_secret_value()}


async def tool(client: AsyncClient, attempt, name: str, **args):
    r = await client.post(
        f"/internal/calls/{attempt.id}/tool/{name}", json=args, headers=internal_headers()
    )
    assert r.status_code == 200, r.text
    return r.json()


async def finish(client: AsyncClient, attempt, **body):
    r = await client.patch(
        f"/internal/calls/{attempt.id}", json={"outcome": "conversation", **body},
        headers=internal_headers(),
    )  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


# --- auth -------------------------------------------------------------------------------------


async def test_internal_requires_secret(client: AsyncClient, attempt, admin_headers) -> None:
    url = f"/internal/dispatch-context/{attempt.id}"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers={"X-Internal-Secret": "nope"})).status_code == 401
    assert (await client.get(url, headers=admin_headers)).status_code == 401  # JWT is not enough
    assert (await client.get(url, headers=internal_headers())).status_code == 200


async def test_internal_secret_unset_is_503(client: AsyncClient, attempt, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "internal_api_secret", None)
    r = await client.get(
        f"/internal/dispatch-context/{attempt.id}", headers={"X-Internal-Secret": "x"}
    )
    assert r.status_code == 503


# --- dispatch context -------------------------------------------------------------------------


async def test_dispatch_context(client: AsyncClient, attempt, lead) -> None:
    r = await client.get(f"/internal/dispatch-context/{attempt.id}", headers=internal_headers())
    ctx = r.json()
    assert ctx["phone"] == PHONE and ctx["trunk_id"] == "ST_test"
    assert ctx["caller_id"] == "+12014621616"
    assert ctx["lead"]["contact_name"] == "Abbie"
    assert ctx["playbook"]["persona"]["agent_name"] == "Maria"
    assert ctx["prospect_timezone"] == "America/New_York"
    assert len(ctx["slots"]) == 4 and ctx["slots"][0]["label"]


async def test_dispatch_context_rechecks_allowlist(
    client: AsyncClient, attempt, ready_campaign, db_session
) -> None:
    ready_campaign.test_allowlist = ["+12125550199"]
    await db_session.flush()
    r = await client.get(f"/internal/dispatch-context/{attempt.id}", headers=internal_headers())
    assert r.status_code == 409 and "allowlist" in r.text


async def test_dispatch_context_unknown_attempt(client: AsyncClient) -> None:
    r = await client.get(f"/internal/dispatch-context/{uuid.uuid4()}", headers=internal_headers())
    assert r.status_code == 404


# --- tools ------------------------------------------------------------------------------------


async def test_book_appointment_flow(client: AsyncClient, attempt, lead, db_session) -> None:
    slots = (await tool(client, attempt, "check_slots", preferred_part_of_day="afternoon"))["slots"]
    assert slots and all("2:00 PM" in s["label"] for s in slots)

    bad = await tool(client, attempt, "book_appointment", slot_start_iso="2030-01-01T03:00:00")
    assert bad["ok"] is False and bad["slots"]

    booked = await tool(
        client, attempt, "book_appointment", slot_start_iso=slots[0]["start_iso"],
        contact_name="Abbie", email="Abbie@Example.com", notes="wants maps help",
    )  # fmt: skip
    assert booked["ok"] and booked["confirmation"] == slots[0]["label"]
    assert booked["missing"] == []
    again = await tool(client, attempt, "book_appointment", slot_start_iso=slots[0]["start_iso"])
    assert again["already_booked"] and again["appointment_id"] == booked["appointment_id"]
    n = await db_session.scalar(select(func.count()).select_from(Appointment))
    assert n == 1

    appt = await db_session.get(Appointment, uuid.UUID(booked["appointment_id"]))
    assert (appt.end_at - appt.start_at).total_seconds() == 20 * 60
    assert appt.prospect_timezone == "America/New_York" and appt.call_attempt_id == attempt.id
    assert lead.email == "abbie@example.com"

    await tool(client, attempt, "set_stage", stage="close")
    await tool(client, attempt, "set_stage", stage="pitch")  # stage_reached keeps the furthest
    await tool(client, attempt, "end_call", disposition="appointment_set", farewell_said=True)
    # The analysis model disagreeing does not override the booked appointment.
    out = await finish(client, attempt, disposition="not_interested", summary="Booked.")
    assert out["disposition"] == "appointment_set"
    assert out["lead_state"] == {"applied": True, "lead_status": "appointment_set", "attempts": 1}
    await db_session.refresh(attempt)
    assert attempt.stage_reached == "close" and attempt.end_reason == "end_call"
    assert attempt.status == AttemptStatus.completed and attempt.ended_at is not None
    tools = await db_session.scalars(
        select(CallEvent.payload["name"].astext).where(CallEvent.call_attempt_id == attempt.id)
    )
    assert list(tools).count("book_appointment") == 3


async def test_schedule_callback_sets_next_attempt(
    client: AsyncClient, attempt, lead, db_session
) -> None:
    cb = await tool(
        client, attempt, "schedule_callback", relative_text="tomorrow afternoon", reason="busy"
    )
    assert cb["ok"] and cb["understood"] and "2:00 PM" in cb["callback_human"]
    out = await finish(client, attempt)
    assert out["lead_state"]["lead_status"] == "callback"
    await db_session.refresh(lead)
    assert lead.next_attempt_at == datetime.fromisoformat(cb["callback_at"])


async def test_add_to_dnc_is_immediate(client: AsyncClient, attempt, lead, db_session) -> None:
    await tool(client, attempt, "add_to_dnc", reason="asked to stop")
    entry = await db_session.scalar(select(DncEntry).where(DncEntry.phone_e164 == PHONE))
    assert entry is not None and entry.source == "call"
    consent = await db_session.scalar(select(ConsentEvent).where(ConsentEvent.lead_id == lead.id))
    assert consent is not None
    # A later disposition can't downgrade the opt-out.
    await tool(client, attempt, "end_call", disposition="not_interested")
    out = await finish(client, attempt)
    assert out["disposition"] == "dnc" and out["lead_state"]["lead_status"] == "dnc"


@pytest.mark.parametrize(
    ("tool_name", "args", "status"),
    [
        ("mark_not_interested", {"reason": "no"}, "not_interested"),
        ("mark_wrong_number", {"note": "pizza place"}, "wrong_number"),
    ],
)
async def test_mark_tools(client, attempt, tool_name, args, status) -> None:
    assert (await tool(client, attempt, tool_name, **args))["ok"]
    assert (await finish(client, attempt))["lead_state"]["lead_status"] == status


async def test_stub_tools(client: AsyncClient, attempt, db_session) -> None:
    for name in ("send_info", "transfer_to_human", "escalate_complaint"):
        assert (await tool(client, attempt, name))["allowed"] is False
    await db_session.refresh(attempt)
    assert attempt.needs_review is True


async def test_tool_errors(client: AsyncClient, attempt) -> None:
    r = await client.post(
        f"/internal/calls/{attempt.id}/tool/launch_rocket", json={}, headers=internal_headers()
    )
    assert r.status_code == 404
    bad = await tool(client, attempt, "set_stage", stage="dance")
    assert bad["ok"] is False and "invalid arguments" in bad["error"]


# --- events and results -----------------------------------------------------------------------


async def test_events_append_transcript(client: AsyncClient, attempt, db_session) -> None:
    url = f"/internal/calls/{attempt.id}/events"
    for role, text in (("user", "Hello?"), ("assistant", "Hi Abbie, this is Maria.")):
        body = {"type": "turn", "role": role, "text": text, "latency_ms": 700}
        r = await client.post(url, json=body, headers=internal_headers())
        assert r.status_code == 201
    r = await client.post(url, json={"type": "amd", "payload": {"result": "human"}},
                          headers=internal_headers())  # fmt: skip
    assert r.status_code == 201
    assert (
        await client.post(url, json={"type": "turn"}, headers=internal_headers())
    ).status_code == 422
    await db_session.refresh(attempt)
    assert [t["text"] for t in attempt.transcript] == ["Hello?", "Hi Abbie, this is Maria."]
    assert attempt.transcript[0]["latency_ms"] == 700


async def test_no_answer_requeues_and_patch_is_idempotent(
    client: AsyncClient, attempt, lead, db_session
) -> None:
    body = {"outcome": "no_answer", "status": "completed", "sip_status": "480"}
    r = await client.patch(f"/internal/calls/{attempt.id}", json=body, headers=internal_headers())
    assert r.json()["lead_state"]["lead_status"] == "queued"
    # A repeated final PATCH (worker retry) must not apply the state machine twice.
    r = await client.patch(
        f"/internal/calls/{attempt.id}", json={"outcome": "busy"}, headers=internal_headers()
    )
    assert r.json()["lead_state"] == {"applied": False} and r.json()["outcome"] == "no_answer"
    await db_session.refresh(lead)
    assert lead.attempts == 1 and lead.next_attempt_at is not None


async def test_patch_progress_fields(client: AsyncClient, attempt, lead, db_session) -> None:
    body = {"status": "in_call", "amd_result": "human", "answered_at": "2026-10-01T13:00:00Z",
            "human_detected_at": "2026-10-01T13:00:03Z"}  # fmt: skip
    r = await client.patch(f"/internal/calls/{attempt.id}", json=body, headers=internal_headers())
    assert r.status_code == 200 and r.json()["lead_state"] == {"applied": False}
    await db_session.refresh(lead)
    assert lead.status == LeadStatus.calling
    r = await client.patch(
        f"/internal/calls/{attempt.id}", json={"bogus": 1}, headers=internal_headers()
    )
    assert r.status_code == 422
