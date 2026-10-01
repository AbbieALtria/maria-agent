"""System prompt assembly for Maria (docs/outbound/04-CAMPAIGN-PLAYBOOK-SPEC.md §2).

Pure functions so the voice-worker, the API's future /simulate endpoint and snapshot tests all
render the same prompt. Section order follows 04 §2; lead context and "now" are the only per-call
parts.
"""

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from playbook_schema.models import PLACEHOLDER_RE, STAGES, Playbook

# Opt-out phrases that always trigger add_to_dnc, on top of compliance.opt_out_phrases_extra.
BASE_OPT_OUT_PHRASES = (
    "stop calling",
    "don't call me again",
    "do not call",
    "remove me from your list",
    "take me off your list",
    "put me on your do not call list",
)


def lead_value(lead: Mapping[str, Any], field: str) -> Any:
    """Value of a lead field; `custom.x` reads lead["custom"]["x"]."""
    if field.startswith("custom."):
        return (lead.get("custom") or {}).get(field.removeprefix("custom."))
    return lead.get(field)


def placeholder_values(
    playbook: Playbook, lead: Mapping[str, Any], slots: Sequence[Mapping[str, Any]] = ()
) -> dict[str, str]:
    contact = (lead.get("contact_name") or "").strip()
    values = {
        "contact_name_or_the_owner": contact or "the owner",
        "first_name": contact.split()[0] if contact else "there",
        "business_name": lead.get("business_name") or "your business",
        "city": lead.get("city") or "your area",
        "slot_1": slots[0]["label"] if len(slots) > 0 else "<first available slot>",
        "slot_2": slots[1]["label"] if len(slots) > 1 else "<second available slot>",
        "slot_human": "<the slot the prospect agreed to>",
        "rep_or_team": playbook.goal.appointment.with_whom,
        "agent_name": playbook.persona.agent_name,
        "compliance.ai_disclosure_text": playbook.compliance.ai_disclosure_text,
    }
    for field in playbook.lead_context_fields:
        if field not in values:
            v = lead_value(lead, field)
            values[field] = "unknown" if v in (None, "") else str(v)
    return values


def render(text: str, values: Mapping[str, str]) -> str:
    """Replace {placeholders}; unknown ones are left as-is."""
    return PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def _bullets(items: Sequence[str], indent: str = "") -> str:
    return "\n".join(f"{indent}- {i}" for i in items) if items else f"{indent}- (none)"


def _quoted(items: Sequence[str]) -> str:
    return ", ".join(f'"{i}"' for i in items) or "(none)"


def _opt_out_phrases(pb: Playbook) -> list[str]:
    seen: dict[str, None] = {}
    for p in (*BASE_OPT_OUT_PHRASES, *pb.compliance.opt_out_phrases_extra):
        seen.setdefault(p.strip().lower(), None)
    return list(seen)


def _identity(pb: Playbook) -> str:
    p = pb.persona
    return f"""# 1. Identity and honesty
You are {p.agent_name}, a voice appointment coordinator: the {p.role}, calling from {p.company}.
You are on a live outbound phone call with a business owner or employee.
- You are an AI. Never claim or imply that you are human. If anyone asks whether you are a person, a robot or an AI, answer honestly using the disclosure text in section 10.
- Only state facts listed under FACTS. Never invent prices, guarantees, results, names or details. If asked something you don't know, say {pb.goal.appointment.with_whom} will cover it in the appointment.
- Never say any of: {"; ".join(pb.never_say) or "(nothing listed)"}."""  # noqa: E501


def _style(pb: Playbook) -> str:
    s = pb.persona.style
    numbers = (
        'Speak numbers, times and dates as words ("ten thirty", "October second").'
        if s.speak_numbers_as_words
        else "Numbers may be written as digits."
    )
    return f"""# 2. Persona and speaking style
- Tone: {s.tone}. Formality: {s.formality}; mirror the prospect's formality.
- Keep every turn under {s.max_words_per_turn} words. Short sentences. Ask one question at a time.
- Acknowledge what the prospect said before answering or moving on. Natural fillers you may use sparingly: {_quoted(s.fillers)}.
- Avoid these words: {_quoted(s.avoid)}.
- {numbers}
- This is speech: no lists, bullet points, markdown, emojis or stage directions."""  # noqa: E501


def _goal(pb: Playbook) -> str:
    a = pb.goal.appointment
    needs = [
        n for n, req in (("an email", a.require_email), ("an address", a.require_address)) if req
    ]
    return f"""# 3. Campaign goal
Primary goal: {pb.goal.primary.replace("_", " ")}.
Appointment: a {a.duration_min}-minute {a.type} appointment with {a.with_whom}.
What the prospect gets: {a.value_prop_for_meeting}.
Offer {a.offer_slots_count} specific slots at a time, earliest first. Slots must be at least {a.min_lead_time_hours} hours ahead and no more than {a.max_days_ahead} days ahead.
Before booking, collect: {", ".join(needs) if needs else "nothing extra"} (ask after the prospect agrees to a slot)."""  # noqa: E501


def _lead(pb: Playbook, lead: Mapping[str, Any]) -> str:
    lines = []
    for field in pb.lead_context_fields:
        v = lead_value(lead, field)
        lines.append(f"- {field}: {'unknown' if v in (None, '') else v}")
    return "# 4. Who you are calling\n" + ("\n".join(lines) or "- (no lead context)")


def _now(now_local: datetime, slots: Sequence[Mapping[str, Any]]) -> str:
    tz = now_local.tzname() or ""
    stamp = now_local.strftime("%A, %B %d %Y, %I:%M %p").replace(" 0", " ")
    slot_lines = [f"- {s['label']} (slot_start_iso {s['start_iso']})" for s in slots]
    return f"""# 5. Now
Prospect's local time: {stamp} {tz}.
Available slots (prospect's local time):
{chr(10).join(slot_lines) or "- none pre-fetched; call check_slots"}
Use check_slots if the prospect wants a different day or part of the day."""


def _flow(pb: Playbook, values: Mapping[str, str]) -> str:
    f = pb.flow
    r = lambda t: render(t, values)  # noqa: E731
    qualify = [f"{q.key}{' (required)' if q.required else ''}: {r(q.ask)}" for q in f.qualify]
    return f"""# 6. Conversation flow
The lines below are inspiration, not a script: paraphrase naturally, never read two lines back-to-back, and adapt to what the prospect says. Stages (track them with set_stage): {", ".join(STAGES)}.
The phone has just been answered. The prospect's first words are their phone greeting; reply with an opener.
- opener (pick one, vary it):
{_bullets([r(t) for t in f.opener], "  ")}
- permission: {r(f.permission) or "(skip)"}
- reason for call: {r(f.reason_for_call)}
- qualify (weave in, one at a time):
{_bullets(qualify, "  ")}
- pitch points:
{_bullets([r(t) for t in f.pitch_points], "  ")}
- close:
{_bullets([r(t) for t in f.close], "  ")}
- confirm: {r(f.confirm)}
- wrap: {r(f.wrap)}
- gatekeeper (if you reached someone else): {r(f.gatekeeper) or "(ask for the owner)"}"""  # noqa: E501


def _objections(pb: Playbook, values: Mapping[str, str]) -> str:
    rows = []
    for o in pb.objections:
        tool = f" Then call {o.tool}." if o.tool else ""
        said = '" or "'.join(o.trigger.split("|"))
        rows.append(
            f'- When they say something like "{said}": '
            f"{render(o.response, values)} (max {o.max_rebuttals} rebuttal(s).){tool}"
        )
    e = pb.exit_rules
    return f"""# 7. Objections and exit rules
FACTS you may use:
{_bullets(pb.facts)}
Objections:
{chr(10).join(rows) or "- (none)"}
Exit rules:
- At most {e.max_rebuttals_total} rebuttals in total. After the second clear no, say something like: {render(e.on_second_no, values)} Then call mark_not_interested, then end_call.
- If the prospect is hostile or abusive, say something like: {render(e.hostile, values)} Then call add_to_dnc, then end_call.
- Wrong person or business: apologize, call mark_wrong_number, then end_call."""  # noqa: E501


def _tools(pb: Playbook) -> str:
    dispositions = ", ".join(pb.dispositions)
    return f"""# 8. Tools
- set_stage: call whenever the conversation moves to a new stage. It is silent; keep talking.
- check_slots: fetch more slots when the pre-fetched ones don't fit.
- book_appointment: only after the prospect verbally agrees to one specific slot from check_slots or section 5. Then confirm the time back to them.
- schedule_callback: when they ask to be called back at another time.
- mark_not_interested / mark_wrong_number: record the outcome before ending.
- add_to_dnc: immediately when the prospect asks not to be called (see section 10).
- send_info, transfer_to_human, escalate_complaint: may be unavailable; if the result says not allowed, tell the prospect {pb.goal.appointment.with_whom} will follow up.
- end_call: say your farewell first, in the same turn, then call end_call with the disposition. Valid dispositions: {dispositions}.
Never read tool results or ISO timestamps aloud; say times naturally."""  # noqa: E501


def _language(pb: Playbook) -> str:
    lang = pb.language
    switch = (
        f"If the prospect switches to {', '.join(lang.allow_switch_to)}, you may follow them."
        if lang.allow_switch_to
        else "Stay in this language. If the prospect can't continue in it, apologize, "
        "end politely and use disposition language_barrier if available."
    )
    return f"# 9. Language\nSpeak {lang.primary}. {switch}"


def _compliance(pb: Playbook) -> str:
    c = pb.compliance
    disclosure = (
        f'Early in the call, say: "{c.ai_disclosure_text}"'
        if c.ai_disclosure == "upfront"
        else f'If asked whether you are a person, a robot or an AI, say: "{c.ai_disclosure_text}"'
    )
    notice = (
        f'Right after the greeting, say: "{c.recording_notice_text}"'
        if c.recording_notice and c.recording_notice_text
        else "No recording notice is required."
    )
    phrases = _opt_out_phrases(pb)
    return f"""# 10. Compliance
- AI disclosure: {disclosure}
- Recording: {notice}
- Opt-out: if the prospect says anything like {_quoted(phrases)}, immediately call add_to_dnc, then give a short apologetic farewell, then call end_call with disposition dnc. Do not try to rebut an opt-out."""  # noqa: E501


def build_system_prompt(
    playbook: Playbook,
    lead: Mapping[str, Any],
    now_local: datetime,
    slots: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Full system prompt, sections 1–10 of 04 §2."""
    values = placeholder_values(playbook, lead, slots)
    sections = [
        _identity(playbook),
        _style(playbook),
        _goal(playbook),
        _lead(playbook, lead),
        _now(now_local, slots),
        _flow(playbook, values),
        _objections(playbook, values),
        _tools(playbook),
        _language(playbook),
        _compliance(playbook),
    ]
    return "\n\n".join(sections) + "\n"


def opt_out_regex(playbook: Playbook) -> re.Pattern[str]:
    """Case-insensitive regex of all opt-out phrases (for post-call checks and tests)."""
    phrases = _opt_out_phrases(playbook)
    return re.compile("|".join(re.escape(p) for p in phrases), re.IGNORECASE)


def analysis_context(playbook: Playbook) -> str:
    """Compact JSON of what the post-call analysis needs to know about the campaign."""
    return json.dumps(
        {
            "dispositions": playbook.dispositions,
            "qualify_keys": [q.key for q in playbook.flow.qualify],
            "post_call_extract": playbook.post_call_extract,
            "stages": list(STAGES),
        },
        ensure_ascii=False,
    )
