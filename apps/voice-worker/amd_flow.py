"""Dialing and answering-machine detection (docs/outbound/02-ARCHITECTURE.md §2 steps 2–3).

Uses livekit-agents' built-in AMD helper (livekit.agents.voice.amd, 1.8+): it listens to the
callee's greeting through the session's own STT and classifies it with our Haiku-class model.
"""

from dataclasses import dataclass

# AMD category → (call_attempts.amd_result, call_attempts.outcome when not human)
AMD_MAP: dict[str, tuple[str, str | None]] = {
    "human": ("human", None),
    "machine-vm": ("machine_vm", "voicemail"),
    "machine-ivr": ("machine_ivr", "ivr"),
    "machine-unavailable": ("machine_unavailable", "no_human"),
    "uncertain": ("uncertain", "no_human"),
}

BUSY = {486, 600, 603}
NO_ANSWER = {408, 480, 487}
INVALID = {404, 410, 484, 485, 604}


@dataclass(frozen=True)
class DialFailure:
    outcome: str  # busy | no_answer | invalid_number | failed
    sip_status: str | None
    sip_error: str


def map_amd(category: str) -> tuple[str, str | None]:
    return AMD_MAP.get(category, ("uncertain", "no_human"))


def map_sip_error(status_code: int | None, status: str | None, message: str) -> DialFailure:
    if status_code in BUSY:
        outcome = "busy"
    elif status_code in NO_ANSWER:
        outcome = "no_answer"
    elif status_code in INVALID:
        outcome = "invalid_number"
    else:
        outcome = "failed"
    code = str(status_code) if status_code is not None else None
    detail = " ".join(p for p in (code, status) if p) or message
    return DialFailure(outcome=outcome, sip_status=code, sip_error=detail[:500])
