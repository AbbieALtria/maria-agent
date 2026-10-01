"""Post-call analysis (docs/outbound/04-CAMPAIGN-PLAYBOOK-SPEC.md §6) and call metrics.

The analysis model returns structured output validated by Pydantic; it is converted to the 04 §6
result JSON stored in call_attempts.result.
"""

import json
import logging
import math
from collections.abc import Sequence
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError

from playbook_schema import Playbook
from playbook_schema.prompt import analysis_context

log = logging.getLogger("maria.worker.postcall")


class KeyValue(BaseModel):
    key: str
    value: str | None


class ObjectionSeen(BaseModel):
    text: str
    handled: bool


class Analysis(BaseModel):
    """Structured-output schema (free-form maps are key/value lists: strict schemas need fixed
    properties)."""

    disposition: str
    confidence: float = Field(ge=0, le=1)
    summary: str
    stage_reached: str
    qualification: list[KeyValue]
    objections: list[ObjectionSeen]
    extracted: list[KeyValue]
    sentiment: Literal["positive", "neutral", "negative"]
    prospect_language: str
    ai_disclosure_asked: bool
    compliance_flags: list[str]
    needs_review: bool
    review_reason: str | None
    coaching_notes: str

    def to_result(self) -> dict[str, Any]:
        out = self.model_dump()
        out["qualification"] = {kv.key: kv.value for kv in self.qualification}
        out["extracted"] = {kv.key: kv.value for kv in self.extracted}
        return out


SYSTEM = """You review outbound appointment-setting calls made by Maria, an AI voice agent.
Read the transcript and the tool calls, then fill in the result fields.
- disposition: one of the campaign's disposition keys. If book_appointment succeeded it is appointment_set; if add_to_dnc was called it is dnc.
- qualification: one entry per qualify key (value null when not learned). extracted: one entry per post_call_extract field (value null when not mentioned).
- stage_reached: the furthest stage the conversation reached.
- compliance_flags: any of "claimed_human", "fact_outside_playbook", "ignored_opt_out", "pressure_after_no"; empty when clean.
- needs_review: true when confidence < 0.7, any compliance flag, a complaint, or the outcome is unclear.
- coaching_notes: one or two sentences on what Maria could do better.
Base everything on the transcript only."""  # noqa: E501


def transcript_text(turns: Sequence[dict[str, Any]]) -> str:
    who = {"user": "Prospect", "assistant": "Maria"}
    return "\n".join(f"{who.get(t['role'], t['role'])}: {t['text']}" for t in turns)


async def analyze(
    client: anthropic.AsyncAnthropic,
    playbook: Playbook,
    turns: Sequence[dict[str, Any]],
    tool_calls: Sequence[str],
) -> dict[str, Any]:
    """Run the analysis model. Never raises: on failure returns a needs_review stub."""
    user = (
        f"Campaign context: {analysis_context(playbook)}\n"
        f"Tools Maria called, in order: {json.dumps(list(tool_calls))}\n\n"
        f"Transcript:\n{transcript_text(turns) or '(empty)'}"
    )
    try:
        response = await client.messages.parse(
            model=playbook.models.analysis,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "medium"},
            output_format=Analysis,
        )
    except (anthropic.APIError, ValidationError, ValueError) as exc:
        # API failure, or output that failed client-side schema validation.
        log.error("analysis failed", extra={"error": type(exc).__name__})
        return _review_stub(f"analysis failed: {type(exc).__name__}")
    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.warning("analysis returned no result", extra={"stop_reason": response.stop_reason})
        return _review_stub(f"analysis stop_reason={response.stop_reason}")
    return response.parsed_output.to_result()


def _review_stub(reason: str) -> dict[str, Any]:
    return {
        "disposition": None,
        "confidence": 0.0,
        "summary": "",
        "needs_review": True,
        "review_reason": reason,
    }


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def latency_stats(latencies_ms: Sequence[int]) -> dict[str, Any]:
    return {
        "turns": len(latencies_ms),
        "latency_p50_ms": percentile(latencies_ms, 50),
        "latency_p95_ms": percentile(latencies_ms, 95),
    }


def conversation_outcome(user_turns: int, disposition: str | None) -> str:
    """A human answered: was it a conversation or did they hang up straight away?"""
    if disposition or user_turns >= 2:
        return "conversation"
    return "hung_up_early"
