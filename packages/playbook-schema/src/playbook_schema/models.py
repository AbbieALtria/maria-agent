"""Pydantic models for campaign playbooks (docs/outbound/04-CAMPAIGN-PLAYBOOK-SPEC.md §1, §4, §7).

A playbook is the only place campaign-specific behaviour lives. `Playbook.model_validate(data)`
runs the structural checks plus the §7 validation rules; `export_json_schema()` gives the JSON
Schema for editors and the API's validate endpoint.
"""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION = "1.0"

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# Placeholders always available when rendering playbook text (04 §7).
BASE_PLACEHOLDERS = frozenset(
    {
        "contact_name_or_the_owner",
        "first_name",
        "business_name",
        "city",
        "slot_1",
        "slot_2",
        "slot_human",
        "rep_or_team",
        "agent_name",
        "compliance.ai_disclosure_text",
    }
)
REQUIRED_DISPOSITIONS = ("appointment_set", "not_interested", "dnc", "wrong_number", "callback")
MAX_OPENER_WORDS = 60
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][\w.]*)\}")

Stage = Literal[
    "opener", "permission", "qualify", "pitch", "handle_objections", "close", "confirm", "wrap"
]
STAGES: tuple[str, ...] = Stage.__args__  # type: ignore[attr-defined]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Meta(_Model):
    campaign_name: NonEmpty
    client: str = ""
    market: Literal["US", "CA", "PH", "OTHER"] = "US"
    notes: str = ""


class Style(_Model):
    tone: str = "warm, upbeat, concise, professional-casual"
    formality: str = "casual-professional"
    max_words_per_turn: int = Field(default=35, ge=5, le=120)
    fillers: list[str] = []
    avoid: list[str] = []
    speak_numbers_as_words: bool = True


class Persona(_Model):
    agent_name: NonEmpty = "Maria"
    company: NonEmpty
    role: NonEmpty
    voice_id: NonEmpty
    style: Style = Style()


class SttSettings(_Model):
    model: NonEmpty = "nova-3"
    language: NonEmpty = "en"


class TtsSettings(_Model):
    model: NonEmpty = "eleven_flash_v2_5"
    language_code: str | None = None


class Language(_Model):
    primary: NonEmpty = "en-US"
    allow_switch_to: list[str] = []
    stt: SttSettings = SttSettings()
    tts: TtsSettings = TtsSettings()


class Models(_Model):
    # The livekit Anthropic plugin (1.8.x) does not round-trip thinking blocks, so the live model
    # must run without thinking: Sonnet 4.6 does unless asked. Analysis calls the SDK directly.
    live: NonEmpty = "claude-sonnet-4-6"
    analysis: NonEmpty = "claude-sonnet-5-5"
    amd: NonEmpty = "claude-haiku-4-5"


class Compliance(_Model):
    ai_disclosure: Literal["on_ask", "upfront"] = "on_ask"
    ai_disclosure_text: NonEmpty
    recording_notice: bool = False
    recording_notice_text: str = ""
    opt_out_phrases_extra: list[str] = []


class AppointmentGoal(_Model):
    type: Literal["phone", "video", "onsite"] = "phone"
    duration_min: int = Field(default=20, ge=5, le=240)
    with_whom: NonEmpty
    value_prop_for_meeting: NonEmpty
    min_lead_time_hours: int = Field(default=24, ge=0)
    max_days_ahead: int = Field(default=10, ge=1, le=60)
    offer_slots_count: int = Field(default=2, ge=1, le=4)
    require_email: bool = False
    require_address: bool = False


class Goal(_Model):
    primary: Literal["book_appointment", "qualify_only", "callback"] = "book_appointment"
    appointment: AppointmentGoal


class QualifyQuestion(_Model):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    ask: NonEmpty
    type: Literal["bool", "text", "number", "choice"] = "text"
    required: bool = False
    choices: list[str] | None = None


class Voicemail(_Model):
    leave_message: bool = False
    text: str = ""


class Ivr(_Model):
    dtmf: str | None = None
    max_wait_sec: int = Field(default=8, ge=0, le=60)


class Flow(_Model):
    opener: list[NonEmpty] = Field(min_length=1)
    permission: str = ""
    reason_for_call: NonEmpty
    qualify: list[QualifyQuestion] = []
    pitch_points: list[NonEmpty] = []
    close: list[NonEmpty] = Field(min_length=1)
    confirm: NonEmpty
    wrap: NonEmpty
    voicemail: Voicemail = Voicemail()
    ivr: Ivr = Ivr()
    gatekeeper: str = ""


ToolName = Literal[
    "check_slots",
    "book_appointment",
    "schedule_callback",
    "mark_not_interested",
    "mark_wrong_number",
    "add_to_dnc",
    "send_info",
    "transfer_to_human",
    "escalate_complaint",
    "set_stage",
    "end_call",
]


class Objection(_Model):
    trigger: NonEmpty  # regex, case-insensitive
    response: NonEmpty
    max_rebuttals: int = Field(default=1, ge=0, le=99)
    tool: ToolName | None = None


class ExitRules(_Model):
    max_rebuttals_total: int = Field(default=2, ge=0, le=10)
    on_second_no: NonEmpty
    hostile: NonEmpty
    max_duration_sec: int = Field(default=480, ge=30, le=3600)
    silence_timeout_sec: int = Field(default=12, ge=3, le=120)


class Notifications(_Model):
    prospect_confirmation: dict[str, Any] = {}
    team: dict[str, Any] = {}


class Runtime(_Model):
    min_endpointing_delay: float = Field(default=0.5, ge=0.1, le=3.0)
    max_endpointing_delay: float = Field(default=3.0, ge=0.5, le=10.0)
    allow_interruptions: bool = True
    preemptive_generation: bool = True
    greeting_delay_ms: int = Field(default=600, ge=0, le=5000)
    background_noise: str | None = None


class Playbook(_Model):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    meta: Meta
    persona: Persona
    language: Language = Language()
    models: Models = Models()
    compliance: Compliance
    goal: Goal
    lead_context_fields: list[NonEmpty] = []
    facts: list[NonEmpty] = []
    never_say: list[str] = []
    flow: Flow
    objections: list[Objection] = []
    exit_rules: ExitRules
    dispositions: dict[str, NonEmpty]
    post_call_extract: list[NonEmpty] = []
    notifications: Notifications = Notifications()
    runtime: Runtime = Runtime()

    @property
    def known_placeholders(self) -> frozenset[str]:
        return BASE_PLACEHOLDERS | frozenset(self.lead_context_fields)

    def templated_texts(self) -> list[tuple[str, str]]:
        """(location, text) for every string that may contain {placeholders}."""
        f = self.flow
        out: list[tuple[str, str]] = [(f"flow.opener[{i}]", t) for i, t in enumerate(f.opener)]
        out += [
            ("flow.permission", f.permission),
            ("flow.reason_for_call", f.reason_for_call),
            ("flow.confirm", f.confirm),
            ("flow.wrap", f.wrap),
            ("flow.voicemail.text", f.voicemail.text),
            ("flow.gatekeeper", f.gatekeeper),
            ("exit_rules.on_second_no", self.exit_rules.on_second_no),
            ("exit_rules.hostile", self.exit_rules.hostile),
        ]
        out += [(f"flow.qualify[{i}].ask", q.ask) for i, q in enumerate(f.qualify)]
        out += [(f"flow.pitch_points[{i}]", t) for i, t in enumerate(f.pitch_points)]
        out += [(f"flow.close[{i}]", t) for i, t in enumerate(f.close)]
        out += [(f"objections[{i}].response", o.response) for i, o in enumerate(self.objections)]
        return out

    @model_validator(mode="after")
    def _rules(self) -> "Playbook":
        """04 §7 validation rules. All problems are reported together."""
        errors: list[str] = []
        known = self.known_placeholders
        for where, text in self.templated_texts():
            for name in PLACEHOLDER_RE.findall(text):
                if name not in known:
                    errors.append(f"{where}: unknown placeholder {{{name}}}")
        for i, o in enumerate(self.objections):
            try:
                re.compile(o.trigger, re.IGNORECASE)
            except re.error as exc:
                errors.append(f"objections[{i}].trigger: invalid regex ({exc})")
        for i, text in enumerate(self.flow.opener):
            if len(text.split()) > MAX_OPENER_WORDS:
                errors.append(f"flow.opener[{i}]: more than {MAX_OPENER_WORDS} words")
        missing = [d for d in REQUIRED_DISPOSITIONS if d not in self.dispositions]
        if missing:
            errors.append(f"dispositions: missing {', '.join(missing)}")
        appt = self.goal.appointment
        if appt.type == "onsite" and not appt.require_address:
            errors.append("goal.appointment: type onsite requires require_address = true")
        if errors:
            raise ValueError("\n".join(errors))
        return self


def export_json_schema() -> dict[str, Any]:
    schema = Playbook.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = f"Maria campaign playbook v{SCHEMA_VERSION}"
    return schema


def validation_errors(data: Any) -> list[str]:
    """Human-readable validation errors ([] when valid)."""
    from pydantic import ValidationError

    try:
        Playbook.model_validate(data)
    except ValidationError as exc:
        out = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            for msg in err["msg"].removeprefix("Value error, ").split("\n"):
                out.append(f"{loc}: {msg}" if loc else msg)
        return out
    return []
