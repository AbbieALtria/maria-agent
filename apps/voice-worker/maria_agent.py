"""MariaAgent: one generic Agent per call, built entirely from the campaign playbook
(docs/outbound/02-ARCHITECTURE.md §3, 04-CAMPAIGN-PLAYBOOK-SPEC.md §2–3).

Tools forward to the API (`/internal/calls/{id}/tool/{name}`); the API owns all CRM effects.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from livekit.agents import Agent, RunContext, ToolResult, function_tool

from crm_client import CrmClient, CrmError
from playbook_schema import Playbook, build_system_prompt
from playbook_schema.prompt import placeholder_values, render

log = logging.getLogger("maria.worker.agent")

TOOL_UNAVAILABLE = {
    "ok": False,
    "error": "the system is unavailable; do not promise anything, offer a follow-up call",
}

# Dispositions that tools set; the worker uses them to decide the call outcome.
TOOL_DISPOSITIONS = {
    "book_appointment": "appointment_set",
    "schedule_callback": "callback",
    "mark_not_interested": "not_interested",
    "mark_wrong_number": "wrong_number",
    "add_to_dnc": "dnc",
}


class MariaAgent(Agent):
    def __init__(
        self,
        *,
        playbook: Playbook,
        lead: dict[str, Any],
        now_local: datetime,
        slots: list[dict[str, Any]],
        crm: CrmClient,
        attempt_id: str,
        on_hangup: Callable[[str], None],
    ) -> None:
        super().__init__(instructions=build_system_prompt(playbook, lead, now_local, slots))
        self.playbook = playbook
        self.lead = lead
        self.slots = slots
        self._crm = crm
        self._attempt_id = attempt_id
        self._on_hangup = on_hangup
        self.tool_calls: list[str] = []
        self.disposition: str | None = None
        self.stage: str | None = None

    def farewell(self) -> str:
        return render(self.playbook.flow.wrap, placeholder_values(self.playbook, self.lead))

    async def _forward(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.tool_calls.append(name)
        args = {k: v for k, v in args.items() if v is not None}
        try:
            result = await self._crm.tool(self._attempt_id, name, args)
        except CrmError as exc:
            log.error("tool failed", extra={"tool": name, "status": exc.status})
            return TOOL_UNAVAILABLE
        if name in TOOL_DISPOSITIONS and result.get("ok"):
            self.disposition = _stronger(self.disposition, TOOL_DISPOSITIONS[name])
        log.info("tool", extra={"tool": name, "ok": result.get("ok", result.get("allowed"))})
        return result

    # --- tools (03 §4) ----------------------------------------------------------------------

    @function_tool
    async def check_slots(
        self,
        preferred_day: str | None = None,
        preferred_part_of_day: Literal["morning", "afternoon", "evening"] | None = None,
        count: int | None = None,
    ) -> dict[str, Any]:
        """Get available appointment slots in the prospect's local time.

        Args:
            preferred_day: Day the prospect prefers: a weekday name, "tomorrow", or YYYY-MM-DD.
            preferred_part_of_day: morning, afternoon or evening.
            count: How many slots to return (1-4).
        """
        return await self._forward("check_slots", locals_without_self(locals()))

    @function_tool
    async def book_appointment(
        self,
        slot_start_iso: str,
        contact_name: str | None = None,
        email: str | None = None,
        address: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Book the appointment. Only call after the prospect verbally agreed to this exact slot.

        Args:
            slot_start_iso: The slot_start_iso of the agreed slot, exactly as given.
            contact_name: Name of the person the specialist will meet.
            email: Email for the calendar invite, if given.
            address: Address, only for onsite appointments.
            notes: Short notes for the specialist (needs, pain points).
        """
        return await self._forward("book_appointment", locals_without_self(locals()))

    @function_tool
    async def schedule_callback(
        self,
        reason: str,
        when_iso: str | None = None,
        relative_text: str | None = None,
    ) -> dict[str, Any]:
        """Schedule a callback when the prospect asks to be called another time.

        Args:
            reason: Why a callback is needed.
            when_iso: Exact callback time in ISO 8601, if the prospect gave one.
            relative_text: The prospect's words, e.g. "tomorrow afternoon", if no exact time.
        """
        return await self._forward("schedule_callback", locals_without_self(locals()))

    @function_tool
    async def mark_not_interested(self, reason: str) -> dict[str, Any]:
        """Record that the prospect is not interested (after exit rules are exhausted).

        Args:
            reason: Their reason, in a few words.
        """
        return await self._forward("mark_not_interested", {"reason": reason})

    @function_tool
    async def mark_wrong_number(self, note: str) -> dict[str, Any]:
        """Record that this is the wrong number or the wrong business.

        Args:
            note: What the person said.
        """
        return await self._forward("mark_wrong_number", {"note": note})

    @function_tool
    async def add_to_dnc(self, reason: str) -> dict[str, Any]:
        """Add the prospect to the do-not-call list. Call immediately on any opt-out request.

        Args:
            reason: The prospect's words.
        """
        return await self._forward("add_to_dnc", {"reason": reason})

    @function_tool
    async def send_info(self, channel: Literal["sms", "email"], template_key: str) -> dict:
        """Send the prospect information by SMS or email.

        Args:
            channel: sms or email.
            template_key: Which information to send, e.g. "overview".
        """
        return await self._forward("send_info", {"channel": channel, "template_key": template_key})

    @function_tool
    async def transfer_to_human(self, reason: str) -> dict[str, Any]:
        """Transfer the call to a human, if allowed.

        Args:
            reason: Why the prospect wants a person.
        """
        return await self._forward("transfer_to_human", {"reason": reason})

    @function_tool
    async def escalate_complaint(self, summary: str) -> dict[str, Any]:
        """Escalate a complaint about us or a previous contact for a manager to review.

        Args:
            summary: One-sentence summary of the complaint.
        """
        return await self._forward("escalate_complaint", {"summary": summary})

    @function_tool
    async def set_stage(
        self,
        stage: Literal[
            "opener",
            "permission",
            "qualify",
            "pitch",
            "handle_objections",
            "close",
            "confirm",
            "wrap",
        ],  # fmt: skip
    ) -> ToolResult:
        """Record the conversation stage you are moving into. Silent: keep talking normally.

        Args:
            stage: The new stage.
        """
        self.stage = stage
        await self._forward("set_stage", {"stage": stage})
        return ToolResult({"ok": True}, reply_required=False)

    @function_tool
    async def end_call(
        self, ctx: RunContext, disposition: str, farewell_said: bool = True
    ) -> ToolResult:
        """End the call. Say your farewell first, in the same turn, then call this.

        Args:
            disposition: The call disposition (one of the playbook's dispositions).
            farewell_said: Whether you already said goodbye in this turn.
        """
        await self._forward(
            "end_call", {"disposition": disposition, "farewell_said": farewell_said}
        )
        self.disposition = _stronger(self.disposition, disposition)
        if farewell_said:
            # Hang up once the farewell in this turn has finished playing.
            ctx.speech_handle.add_done_callback(lambda _: self._on_hangup("end_call"))
        else:
            handle = self.session.say(self.farewell(), allow_interruptions=False)
            handle.add_done_callback(lambda _: self._on_hangup("end_call"))
        return ToolResult({"ok": True}, reply_required=False)


PRIORITY = {
    "dnc": 100,
    "appointment_set": 90,
    "wrong_number": 80,
    "callback": 70,
    "not_interested": 60,
}


def _stronger(current: str | None, new: str | None) -> str | None:
    """Mirror of the API's disposition precedence (app/dialer/calls.DISPOSITION_PRIORITY)."""
    if not new:
        return current
    if current is None or PRIORITY.get(new, 10) >= PRIORITY.get(current, 10):
        return new
    return current


def locals_without_self(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k not in ("self", "ctx")}
