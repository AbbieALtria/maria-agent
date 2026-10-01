import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from amd_flow import map_amd, map_sip_error
from crm_client import CrmClient, CrmError
from maria_agent import TOOL_UNAVAILABLE, MariaAgent, _stronger
from playbook_schema import EXAMPLES_DIR, Playbook
from postcall import (
    Analysis,
    KeyValue,
    analyze,
    conversation_outcome,
    latency_stats,
    percentile,
    transcript_text,
)

PLAYBOOK = Playbook.model_validate(
    json.loads((EXAMPLES_DIR / "yp_seo_us.json").read_text(encoding="utf-8"))
)


# --- amd / sip --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "outcome"),
    [(486, "busy"), (603, "busy"), (480, "no_answer"), (408, "no_answer"),
     (404, "invalid_number"), (484, "invalid_number"), (503, "failed"), (None, "failed")],
)  # fmt: skip
def test_map_sip_error(code, outcome) -> None:
    f = map_sip_error(code, "Busy Here" if code == 486 else None, "boom")
    assert f.outcome == outcome
    assert f.sip_status == (str(code) if code else None)
    assert f.sip_error


def test_map_amd() -> None:
    assert map_amd("human") == ("human", None)
    assert map_amd("machine-vm") == ("machine_vm", "voicemail")
    assert map_amd("machine-ivr") == ("machine_ivr", "ivr")
    assert map_amd("uncertain") == ("uncertain", "no_human")
    assert map_amd("something-new") == ("uncertain", "no_human")


# --- post-call --------------------------------------------------------------------------------


def test_latency_stats() -> None:
    assert percentile([], 50) is None
    stats = latency_stats([900, 700, 1200, 800, 3000])
    assert stats == {"turns": 5, "latency_p50_ms": 900, "latency_p95_ms": 3000}


def test_conversation_outcome() -> None:
    assert conversation_outcome(1, None) == "hung_up_early"
    assert conversation_outcome(1, "dnc") == "conversation"
    assert conversation_outcome(3, None) == "conversation"


def _analysis() -> Analysis:
    return Analysis(
        disposition="appointment_set", confidence=0.9, summary="Booked Fri 10am.",
        stage_reached="confirm",
        qualification=[KeyValue(key="decision_maker", value="yes")],
        objections=[], extracted=[KeyValue(key="email", value="a@b.co")],
        sentiment="positive", prospect_language="en", ai_disclosure_asked=False,
        compliance_flags=[], needs_review=False, review_reason=None, coaching_notes="Good.",
    )  # fmt: skip


def test_analysis_to_result_matches_spec_shape() -> None:
    r = _analysis().to_result()
    assert r["qualification"] == {"decision_maker": "yes"}
    assert r["extracted"] == {"email": "a@b.co"}
    assert r["disposition"] == "appointment_set" and r["sentiment"] == "positive"


class FakeMessages:
    def __init__(self, result=None, exc=None, stop_reason="end_turn") -> None:
        self.result, self.exc, self.stop_reason, self.kwargs = result, exc, stop_reason, None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return SimpleNamespace(parsed_output=self.result, stop_reason=self.stop_reason)


async def test_analyze() -> None:
    turns = [{"role": "user", "text": "Hello?"}, {"role": "assistant", "text": "Hi, Maria here."}]
    msgs = FakeMessages(result=_analysis())
    out = await analyze(SimpleNamespace(messages=msgs), PLAYBOOK, turns, ["book_appointment"])
    assert out["disposition"] == "appointment_set"
    assert msgs.kwargs["model"] == PLAYBOOK.models.analysis
    assert msgs.kwargs["output_format"] is Analysis
    assert "Prospect: Hello?" in msgs.kwargs["messages"][0]["content"]


async def test_analyze_failures_need_review() -> None:
    refusal = FakeMessages(result=None, stop_reason="refusal")
    out = await analyze(SimpleNamespace(messages=refusal), PLAYBOOK, [], [])
    assert out["needs_review"] and "refusal" in out["review_reason"]
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIConnectionError(request=req)
    out = await analyze(SimpleNamespace(messages=FakeMessages(exc=err)), PLAYBOOK, [], [])
    assert out["needs_review"] and "APIConnectionError" in out["review_reason"]


def test_transcript_text() -> None:
    assert transcript_text([{"role": "assistant", "text": "Hi"}]) == "Maria: Hi"


# --- CRM client -------------------------------------------------------------------------------


async def test_crm_client_retries_5xx_and_sends_secret() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) < 3:
            return httpx.Response(503, json={"detail": "busy"})
        return httpx.Response(200, json={"ok": True})

    crm = CrmClient("http://api", "s3cret", transport=httpx.MockTransport(handler))
    assert await crm.tool("att-1", "set_stage", {"stage": "pitch"}) == {"ok": True}
    assert len(seen) == 3
    assert seen[0].headers["X-Internal-Secret"] == "s3cret"
    assert seen[0].url.path == "/internal/calls/att-1/tool/set_stage"
    await crm.aclose()


async def test_crm_client_4xx_is_not_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(409, json={"detail": "phone not in test allowlist"})

    crm = CrmClient("http://api", "s", transport=httpx.MockTransport(handler))
    with pytest.raises(CrmError) as exc:
        await crm.dispatch_context("att-1")
    assert exc.value.status == 409 and "allowlist" in exc.value.detail and len(calls) == 1


# --- agent ------------------------------------------------------------------------------------


class FakeCrm:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = fail

    async def tool(self, attempt_id: str, name: str, args: dict) -> dict:
        if self.fail:
            raise CrmError(503, "down")
        self.calls.append((name, args))
        return {"ok": True}


def _agent(crm) -> MariaAgent:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return MariaAgent(
        playbook=PLAYBOOK, lead={"id": "l1", "contact_name": "Abbie Smith"},
        now_local=datetime(2026, 10, 1, 9, tzinfo=ZoneInfo("America/New_York")), slots=[],
        crm=crm, attempt_id="att-1", on_hangup=lambda reason: None,
    )  # fmt: skip


async def test_agent_forwarding_and_dispositions() -> None:
    crm = FakeCrm()
    agent = _agent(crm)
    assert "You are Maria" in agent.instructions
    assert len(agent.tools) == 11
    await agent._forward("check_slots", {"preferred_day": "friday", "count": None})
    assert crm.calls[-1] == ("check_slots", {"preferred_day": "friday"})  # None args dropped
    await agent._forward("book_appointment", {"slot_start_iso": "x"})
    await agent._forward("mark_not_interested", {"reason": "later"})
    assert agent.disposition == "appointment_set"  # a booking outranks a later "no"
    await agent._forward("add_to_dnc", {"reason": "stop"})
    assert agent.disposition == "dnc"
    assert agent.tool_calls == [
        "check_slots", "book_appointment", "mark_not_interested", "add_to_dnc",
    ]  # fmt: skip
    assert agent.farewell().startswith("Thanks Abbie")


async def test_agent_tool_failure_is_spoken_safely() -> None:
    agent = _agent(FakeCrm(fail=True))
    assert await agent._forward("book_appointment", {"slot_start_iso": "x"}) == TOOL_UNAVAILABLE
    assert agent.disposition is None


def test_stronger() -> None:
    assert _stronger(None, "interested_no_slot") == "interested_no_slot"
    assert _stronger("callback", "not_interested") == "callback"
    assert _stronger("appointment_set", "dnc") == "dnc"
    assert _stronger("dnc", None) == "dnc"
