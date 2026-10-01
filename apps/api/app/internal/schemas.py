"""Request bodies for the internal (voice-worker) API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.crm.enums import AmdResult, AttemptStatus, CallOutcome


class CallPatch(BaseModel):
    """PATCH /internal/calls/{id}. Sending `outcome` for the first time finishes the attempt and
    applies the lead state machine."""

    model_config = ConfigDict(extra="forbid")

    status: AttemptStatus | None = None
    sip_status: str | None = None
    sip_error: str | None = None
    amd_result: AmdResult | None = None
    outcome: CallOutcome | None = None
    disposition: str | None = None
    started_at: datetime | None = None
    answered_at: datetime | None = None
    human_detected_at: datetime | None = None
    ended_at: datetime | None = None
    duration_sec: int | None = Field(default=None, ge=0)
    talk_sec: int | None = Field(default=None, ge=0)
    result: dict[str, Any] | None = None
    summary: str | None = None
    sentiment: str | None = None
    needs_review: bool | None = None
    review_reason: str | None = None
    stage_reached: str | None = None
    end_reason: str | None = None
    metrics: dict[str, Any] | None = None
    cost_usd: float | None = Field(default=None, ge=0)


class CallEventIn(BaseModel):
    """A transcript turn (type=turn) or any other call event (stage, amd, error, …)."""

    type: str = Field(min_length=1, max_length=64)
    ts: datetime | None = None
    role: Literal["user", "assistant"] | None = None
    text: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = {}
