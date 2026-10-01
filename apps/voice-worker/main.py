"""Maria voice-worker entrypoint (docs/outbound/02-ARCHITECTURE.md §2–3).

    python main.py download-files   # once: turn-detector + VAD model files
    python main.py dev              # local development (scripts/worker.ps1)
    python main.py start            # production

One job = one outbound call: dispatch context → dial (SIP, wait until answered) → AMD →
conversation with MariaAgent → hang up → post-call analysis → PATCH result.
"""

import asyncio
import json
import logging
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any

from worker_config import WorkerConfig, load_env

load_env()

import anthropic  # noqa: E402
from livekit import api  # noqa: E402
from livekit.agents import (  # noqa: E402
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    room_io,
)
from livekit.agents.voice.amd import AMD  # noqa: E402
from livekit.plugins import anthropic as lk_anthropic  # noqa: E402
from livekit.plugins import deepgram, elevenlabs, silero  # noqa: E402
from livekit.plugins.anthropic import llm as lk_anthropic_llm  # noqa: E402
from livekit.plugins.turn_detector.multilingual import MultilingualModel  # noqa: E402

from amd_flow import map_amd, map_sip_error  # noqa: E402
from crm_client import CrmClient, CrmError  # noqa: E402
from maria_agent import MariaAgent  # noqa: E402
from playbook_schema import Playbook  # noqa: E402
from playbook_schema.prompt import placeholder_values, render  # noqa: E402
from postcall import analyze, conversation_outcome, latency_stats  # noqa: E402

logger = logging.getLogger("maria.worker")

# Claude 4.6+ rejects assistant prefill; the plugin only knows the 4.6 names. Harmless for others.
lk_anthropic_llm._NO_PREFILL_PATTERNS = (
    *lk_anthropic_llm._NO_PREFILL_PATTERNS,
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-fable",
)

GREETING_INSTRUCTIONS = (
    "The prospect just answered the phone. Greet them now with a short opener from section 6."
)
STILL_THERE_INSTRUCTIONS = "The line has gone quiet. Briefly and warmly ask if they're still there."
WRAP_UP_INSTRUCTIONS = (
    "The call has reached its time limit. In one short sentence, thank them, say the team will "
    "follow up, and say goodbye."
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class CallLog(logging.LoggerAdapter):
    """Adds attempt_id / campaign_id to every log line in the call path."""

    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> tuple[Any, Any]:
        kwargs["extra"] = {**(self.extra or {}), **(kwargs.get("extra") or {})}
        return msg, kwargs


def parse_metadata(raw: str | None) -> dict[str, Any]:
    meta = json.loads(raw or "{}")
    if not meta.get("attempt_id"):
        raise ValueError("job metadata has no attempt_id")
    return meta


server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    cfg = WorkerConfig.from_env()
    meta = parse_metadata(ctx.job.metadata)
    await OutboundCall(ctx, cfg, meta).run()


class OutboundCall:
    def __init__(self, ctx: JobContext, cfg: WorkerConfig, meta: dict[str, Any]) -> None:
        self.ctx = ctx
        self.meta = meta
        self.attempt_id: str = meta["attempt_id"]
        self.log = CallLog(
            logger, {"attempt_id": self.attempt_id, "campaign_id": meta.get("campaign_id")}
        )
        self.crm = CrmClient(cfg.api_base_url, cfg.internal_api_secret)
        self.finalized = False
        self.end_reason: str | None = None
        self.ended = asyncio.Event()
        self.turns: list[dict[str, Any]] = []
        self.latencies_ms: list[int] = []
        self.answered_at: datetime | None = None
        self.human_at: datetime | None = None
        self.away_count = 0
        self._events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._tasks: list[asyncio.Task[Any]] = []
        self.session: AgentSession | None = None
        self.agent: MariaAgent | None = None

    # --- lifecycle --------------------------------------------------------------------------

    async def run(self) -> None:
        self.ctx.add_shutdown_callback(self._on_shutdown)
        try:
            dctx = await self.crm.dispatch_context(self.attempt_id)
        except CrmError as exc:
            # Refused (test allowlist, invalid playbook, …) or unknown: never dial. Unless the
            # attempt is gone or already finished, _on_shutdown records it as failed so the lead
            # does not stay in `calling`.
            self.log.error("dispatch context refused", extra={"status": exc.status})
            self.finalized = exc.status == 404 or "already finished" in exc.detail
            self.end_reason = "dispatch_refused"
            self.ctx.shutdown(reason="dispatch context refused")
            return
        if dctx["phone"] != self.meta.get("phone"):
            self.log.warning("metadata phone differs from CRM; using the CRM number")
        if not dctx.get("trunk_id") or not dctx.get("caller_id"):
            await self.finish(outcome="failed", status="failed", end_reason="no_trunk")
            return

        playbook = Playbook.model_validate(dctx["playbook"])
        await self.ctx.connect()
        identity = f"phone-{dctx['lead']['id']}"
        session = self.session = self._build_session(playbook)
        agent = self.agent = MariaAgent(
            playbook=playbook,
            lead=dctx["lead"],
            now_local=datetime.fromisoformat(dctx["now_local"]),
            slots=dctx["slots"],
            crm=self.crm,
            attempt_id=self.attempt_id,
            on_hangup=self.request_end,
        )
        self._wire(session)
        self._tasks.append(asyncio.create_task(self._event_sender()))
        await session.start(
            agent=agent,
            room=self.ctx.room,
            room_options=room_io.RoomOptions(participant_identity=identity),
            record=False,  # recording/egress arrives in Phase 2b
        )

        await self._patch(status="ringing", started_at=now_iso())
        self.log.info("dialing", extra={"trunk_id": dctx["trunk_id"]})
        async with AMD(
            session,
            llm=lk_anthropic.LLM(model=playbook.models.amd),
            stt=None,  # reuse the session's Deepgram transcripts
            participant_identity=identity,
            ivr_detection=False,
            suppress_compatibility_warning=True,
        ) as detector:
            try:
                await self.ctx.api.sip.create_sip_participant(
                    api.CreateSIPParticipantRequest(
                        room_name=self.ctx.room.name,
                        sip_trunk_id=dctx["trunk_id"],
                        sip_call_to=dctx["phone"],
                        sip_number=dctx["caller_id"],
                        participant_identity=identity,
                        participant_name=dctx["lead"].get("business_name") or "prospect",
                        wait_until_answered=True,
                        krisp_enabled=True,
                    )
                )
            except api.SipCallError as exc:
                f = map_sip_error(exc.sip_status_code, exc.sip_status, exc.message)
                self.log.info("dial failed", extra={"outcome": f.outcome, "sip": f.sip_status})
                await self.finish(
                    outcome=f.outcome,
                    status="failed" if f.outcome == "failed" else "completed",
                    sip_status=f.sip_status,
                    sip_error=f.sip_error,
                    end_reason="sip_error",
                )
                return
            except api.TwirpError as exc:
                self.log.error("create_sip_participant failed", extra={"code": exc.code})
                await self.finish(
                    outcome="failed", status="failed", sip_error=exc.message[:500],
                    end_reason="sip_error",
                )  # fmt: skip
                return
            self.answered_at = datetime.now(UTC)
            await self._patch(status="in_call", answered_at=self.answered_at.isoformat())
            self.log.info("answered; running AMD")
            prediction = await detector.execute()

        amd_result, machine_outcome = map_amd(prediction.category.value)
        await self._event(
            {"type": "amd", "payload": {"result": amd_result, "reason": prediction.reason,
                                        "delay_s": prediction.delay}}
        )  # fmt: skip
        self.log.info("amd", extra={"amd_result": amd_result, "amd_reason": prediction.reason})
        if machine_outcome:
            vm = playbook.flow.voicemail
            if machine_outcome == "voicemail" and vm.leave_message and vm.text:
                text = render(vm.text, placeholder_values(playbook, dctx["lead"]))
                await session.say(text, allow_interruptions=False)
            await self.finish(
                outcome=machine_outcome, amd_result=amd_result, end_reason=f"amd_{amd_result}"
            )
            return

        self.human_at = datetime.now(UTC)
        await self._patch(amd_result="human", human_detected_at=self.human_at.isoformat())
        await asyncio.sleep(playbook.runtime.greeting_delay_ms / 1000)
        # Usually the reply to the prospect's "hello?" is already queued (AMD held it); only
        # greet explicitly when nothing is pending.
        if (
            session.current_speech is None
            and session.agent_state not in ("thinking", "speaking")
            and session.user_state != "speaking"
        ):
            session.generate_reply(instructions=GREETING_INSTRUCTIONS)
        self._tasks.append(
            asyncio.create_task(self._max_duration(playbook.exit_rules.max_duration_sec))
        )
        await self.ended.wait()
        await self._finish_conversation(playbook)

    def request_end(self, reason: str) -> None:
        if self.end_reason is None:
            self.end_reason = reason
            self.log.info("call ending", extra={"end_reason": reason})
        self.ended.set()

    async def _finish_conversation(self, playbook: Playbook) -> None:
        assert self.session is not None and self.agent is not None
        ended_at = datetime.now(UTC)
        await self._hang_up()
        await self._drain_events()
        user_turns = sum(1 for t in self.turns if t["role"] == "user")
        outcome = conversation_outcome(user_turns, self.agent.disposition)
        result: dict[str, Any] | None = None
        if outcome == "conversation":
            result = await analyze(
                anthropic.AsyncAnthropic(), playbook, self.turns, self.agent.tool_calls
            )
        stats = latency_stats(self.latencies_ms)
        self.log.info("response latency", extra=stats)
        disposition = self.agent.disposition or (result or {}).get("disposition")
        if outcome == "hung_up_early":
            disposition = disposition or "hung_up"
        talk = int((ended_at - self.human_at).total_seconds()) if self.human_at else None
        await self.finish(
            outcome=outcome,
            disposition=disposition,
            ended_at=ended_at.isoformat(),
            talk_sec=talk,
            end_reason=self.end_reason or "unknown",
            result=result,
            summary=(result or {}).get("summary") or None,
            sentiment=(result or {}).get("sentiment"),
            needs_review=bool((result or {}).get("needs_review")),
            review_reason=(result or {}).get("review_reason"),
            metrics={**stats, "tool_calls": self.agent.tool_calls},
        )

    async def finish(self, *, outcome: str, status: str = "completed", **fields: Any) -> None:
        """Final PATCH (applies the lead state machine), hang up, end the job."""
        fields.setdefault("ended_at", now_iso())
        await self._drain_events()
        try:
            out = await self.crm.patch_call(
                self.attempt_id, outcome=outcome, status=status, **fields
            )
            self.finalized = True
            self.log.info(
                "call result saved",
                extra={"outcome": outcome, "disposition": out.get("disposition"),
                       "lead_state": out.get("lead_state")},
            )  # fmt: skip
        except CrmError as exc:
            self.log.error("final PATCH failed", extra={"status": exc.status})
        await self._hang_up()
        for t in self._tasks:
            t.cancel()
        await self.crm.aclose()
        self.ctx.shutdown(reason=f"call finished: {outcome}")

    async def _hang_up(self) -> None:
        if self.session is not None:
            try:
                await self.session.aclose()
            except Exception:  # noqa: BLE001 - best effort while tearing down
                self.log.exception("session close failed")
        try:
            await self.ctx.delete_room()  # disconnects the SIP leg
        except Exception:  # noqa: BLE001
            self.log.warning("delete_room failed")

    async def _on_shutdown(self, *_: Any) -> None:
        if not self.finalized:
            # Crash or unexpected shutdown: never leave the attempt (and lead) in-flight.
            try:
                await self.crm.patch_call(
                    self.attempt_id, outcome="failed", status="failed", ended_at=now_iso(),
                    end_reason=self.end_reason or "worker_shutdown",
                )  # fmt: skip
            except CrmError:
                self.log.error("could not record the failed attempt")

    # --- session ----------------------------------------------------------------------------

    def _build_session(self, playbook: Playbook) -> AgentSession:
        rt = playbook.runtime
        lang = playbook.language
        tts_kwargs: dict[str, Any] = {}
        if lang.tts.language_code:
            tts_kwargs["language"] = lang.tts.language_code
        return AgentSession(
            stt=deepgram.STT(model=lang.stt.model, language=lang.stt.language),
            llm=lk_anthropic.LLM(model=playbook.models.live, caching="ephemeral"),
            tts=elevenlabs.TTS(
                voice_id=playbook.persona.voice_id, model=lang.tts.model, **tts_kwargs
            ),
            vad=self.ctx.proc.userdata["vad"],
            turn_handling={
                "turn_detection": MultilingualModel(),
                "endpointing": {
                    "min_delay": rt.min_endpointing_delay,
                    "max_delay": rt.max_endpointing_delay,
                },
                "interruption": {"enabled": rt.allow_interruptions},
                "preemptive_generation": {"enabled": rt.preemptive_generation},
            },
            user_away_timeout=float(playbook.exit_rules.silence_timeout_sec),
            max_tool_steps=4,
        )

    def _wire(self, session: AgentSession) -> None:
        @session.on("conversation_item_added")
        def _on_item(ev: Any) -> None:
            item = ev.item
            role = getattr(item, "role", None)
            text = getattr(item, "text_content", None)
            if role not in ("user", "assistant") or not text:
                return
            turn: dict[str, Any] = {
                "type": "turn",
                "role": role,
                "text": text,
                "ts": datetime.fromtimestamp(item.created_at, UTC).isoformat(),
            }
            e2e = (item.metrics or {}).get("e2e_latency") if role == "assistant" else None
            if e2e is not None:
                turn["latency_ms"] = int(e2e * 1000)
                self.latencies_ms.append(turn["latency_ms"])
            self.turns.append(turn)
            self._events.put_nowait(turn)

        @session.on("user_state_changed")
        def _on_user_state(ev: Any) -> None:
            if ev.new_state != "away" or self.human_at is None or self.ended.is_set():
                return
            self.away_count += 1
            if self.away_count == 1:
                session.generate_reply(instructions=STILL_THERE_INSTRUCTIONS)
            else:
                assert self.agent is not None
                handle = session.say(self.agent.farewell(), allow_interruptions=False)
                handle.add_done_callback(lambda _: self.request_end("silence_timeout"))

        @session.on("close")
        def _on_close(ev: Any) -> None:
            reason = getattr(ev.reason, "value", str(ev.reason))
            if reason == "participant_disconnected":
                reason = "prospect_hung_up"
            if ev.error is not None:
                self.log.error("session error", extra={"error": type(ev.error).__name__})
                reason = f"error:{type(ev.error).__name__}"
            self.request_end(reason)

    async def _max_duration(self, seconds: int) -> None:
        await asyncio.sleep(seconds)
        if self.ended.is_set() or self.session is None:
            return
        self.log.info("max duration reached")
        handle = self.session.generate_reply(
            instructions=WRAP_UP_INSTRUCTIONS, allow_interruptions=False
        )
        try:
            await asyncio.wait_for(handle.wait_for_playout(), timeout=20)
        except TimeoutError:
            pass
        self.request_end("max_duration")

    # --- CRM I/O ----------------------------------------------------------------------------

    async def _patch(self, **fields: Any) -> None:
        try:
            await self.crm.patch_call(self.attempt_id, **fields)
        except CrmError as exc:
            self.log.error("PATCH failed", extra={"status": exc.status, "fields": list(fields)})

    async def _event(self, event: dict[str, Any]) -> None:
        self._events.put_nowait(event)

    async def _event_sender(self) -> None:
        """Send events in order, without blocking the conversation."""
        while (event := await self._events.get()) is not None:
            try:
                await self.crm.post_event(self.attempt_id, event)
            except CrmError as exc:
                self.log.warning("event not saved", extra={"status": exc.status})
            finally:
                self._events.task_done()
        self._events.task_done()

    async def _drain_events(self) -> None:
        if not self._tasks:  # sender not started yet
            return
        try:
            await asyncio.wait_for(self._events.join(), timeout=10)
        except TimeoutError:
            self.log.warning("some call events were not saved in time")


if __name__ == "__main__":
    cli.run_app(server)
