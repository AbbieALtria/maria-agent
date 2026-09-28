# 02 — Architecture

## 1. Services

| Service (Railway) | Path in monorepo | Tech | Role |
|---|---|---|---|
| `api` | `apps/api/` | FastAPI, SQLAlchemy 2, Alembic, Postgres+pgvector | CRM REST API, dialer scheduler, webhooks, notifications, learning pipeline jobs, auth |
| `voice-worker` | `apps/voice-worker/` | Python 3.11, `livekit-agents` + plugins (`deepgram`, `anthropic`, `elevenlabs`, `silero`), httpx | Registers with LiveKit as agent `maria-outbound`; per call: dial via SIP, AMD, run conversation, call CRM tools, post-call analysis |
| `web` | `apps/web/` | React, TanStack Query, Tailwind | CRM UI (`/crm/*` routes) |
| `worker-jobs` (same image as api with different start cmd) | `apps/api/` | APScheduler or Celery+Redis | Dial scheduler tick (every 10 s), reminders, retention cleanup, batch transcription |
| Postgres | — | Railway Postgres + pgvector | All data |
| Redis (optional) | — | Railway Redis | Queue + locks for the dialer (use Postgres `SELECT … FOR UPDATE SKIP LOCKED` if you want to avoid Redis in v1) |
| Object storage | — | Railway bucket / R2 (S3 API) | Recordings, uploaded training audio |
| LiveKit Cloud | external | — | Rooms, SIP outbound trunk, agent dispatch, egress recording |
| Telnyx / PH trunk | external | SIP | PSTN termination, caller-ID numbers |

Shared code: `packages/playbook-schema/` (Pydantic models + JSON Schema for campaign playbooks, imported by api and voice-worker), `packages/shared/` (phone normalization, timezone lookup, cost calc).

## 2. Outbound call lifecycle

```
1  Scheduler tick (api/dialer):
   pick leads: status in (new, callback_due, retry_due)
     AND campaign.active AND now() within calling window(lead.timezone)
     AND daily_cap not hit AND active_calls(campaign) < concurrency
     AND phone NOT IN dnc
   → create call_attempt(status='dialing'), lead.status='calling'
   → POST LiveKit CreateAgentDispatch(agent='maria-outbound', room=f"call-{attempt_id}",
        metadata={attempt_id, campaign_id, lead_id, phone, trunk_id, caller_id, playbook_version})

2  voice-worker entrypoint(ctx):
   meta = json.loads(ctx.job.metadata)
   playbook = GET api/internal/playbooks/{campaign_id}/{version}   (cached)
   lead     = GET api/internal/leads/{lead_id}
   session  = AgentSession(stt=Deepgram(model='nova-3', language=playbook.stt_language),
                           llm=Anthropic(model=playbook.llm_model),
                           tts=ElevenLabs(model='eleven_flash_v2_5', voice=playbook.voice_id),
                           vad=silero.VAD, turn_detection=multilingual)
   participant = await ctx.api.sip.create_sip_participant(
        CreateSIPParticipantRequest(room_name=ctx.room.name, sip_trunk_id=meta.trunk_id,
             sip_call_to=meta.phone, sip_number=meta.caller_id,
             participant_identity=f"phone-{lead_id}", wait_until_answered=True,
             krisp_enabled=True))
   → on SipCallError: PATCH attempt {sip_status, outcome: busy|no_answer|failed}; ctx.shutdown()

3  AMD:
   async with AMD(session, participant_identity=...) as detector: result = await detector
   human            → start session with MariaAgent(playbook, lead); Maria speaks opener
   machine-vm       → if playbook.voicemail.leave_message: play TTS message; outcome='voicemail'
   machine-ivr      → optional DTMF from playbook.ivr.dtmf; else outcome='ivr'
   machine-unavailable / uncertain(>N s) → outcome='no_human'

4  Conversation:
   MariaAgent system prompt = assemble(playbook, lead, now_local, available_slots_summary)
   tools (function calls) → HTTP to api/internal/calls/{attempt_id}/tool/{name}
   events streamed to api: transcript turns (user/assistant, ts, latency), tool results
   session ends when: end_call tool, prospect hangs up (participant_disconnected),
   max_duration, silence timeout

5  Post-call (voice-worker, then api):
   egress recording finalized → bucket URL stored on attempt
   Claude (analysis model) → structured result JSON (see 04 §6) → PATCH attempt
   api applies state machine: lead.status, next_attempt_at, appointment linkage,
   notifications, webhooks, cost roll-up
```

Recording: use LiveKit Egress room-composite audio-only → S3-compatible bucket. Start egress right after human detected (or at dial if `record_full=true`).

## 3. Maria's conversation design (voice-worker)

- One `Agent` subclass per call, built from the playbook; no campaign-specific classes.
- **Prompt assembly order:** identity & honesty rules → campaign persona & goal → lead context → conversation flow (stages) → objection table → tools usage rules → output style (short sentences, one question at a time, max ~35 words per turn, natural fillers allowed, numbers spoken as words) → language rules → compliance lines.
- **Stages** are guidance, not a rigid state machine: `opener → permission → qualify → pitch → handle_objections → close → confirm → wrap`. Maria tracks `current_stage` in a lightweight state object updated via a `set_stage` internal tool so the CRM can show where calls die.
- **Turn-taking:** LiveKit `MultilingualModel` turn detector + Silero VAD; `allow_interruptions=True`; `min_endpointing_delay` tuned 0.4–0.6 s; preemptive generation on.
- **Human-likeness:** greeting variants randomized; playbook `style.fillers` ("Got it", "Sure", "Ah okay"); avoid lists; ask one thing at a time; acknowledge before answering; mirror prospect's formality; for PH switch to Taglish when the prospect does.
- **Guardrails:** never invent prices/guarantees not in playbook `facts`; if asked something unknown → "I'll have {rep} cover that in the appointment"; if hostile → apologize, offer DNC, end. Keyword triggers for `escalate_complaint` → OmniCX ticket.
- **Latency budget:** STT final ≤ 300 ms after end of speech; LLM first token ≤ 500 ms (Sonnet-class, streaming, prompt cached); TTS first byte ≤ 150 ms.

## 4. Dialer rules (api/dialer)

- Lead selection query uses `FOR UPDATE SKIP LOCKED`; a lead is never dialed twice concurrently.
- Retry policy per campaign: `max_attempts`, `retry_spacing_hours`, `spread_time_of_day` (try morning then afternoon), `voicemail_counts_as_attempt`.
- Callback: `schedule_callback` tool sets `next_attempt_at` exactly (prospect's timezone), overrides window if within 08:00–21:00.
- Watchdog: attempts in `dialing|in_call` older than 15 min → `failed_stale`, lead requeued once.
- Pacing: campaign `concurrency`; global cap from env `MAX_CONCURRENT_CALLS`.
- Cost guard: campaign `daily_budget_usd`; stop dialing when estimated spend exceeds it.

## 5. Repo layout

```
maria-agent/
├─ apps/
│  ├─ api/
│  │  └─ app/
│  │     ├─ crm/         # models, schemas, routers: campaigns, leads, calls, appointments, dnc, users
│  │     ├─ dialer/      # scheduler, livekit_client, state_machine, watchdog
│  │     ├─ learning/    # uploads, transcription, analysis, playbook_drafts, evals
│  │     ├─ notify/      # email, sms, webhooks, ics
│  │     └─ internal/    # endpoints used only by voice-worker (shared secret header)
│  ├─ voice-worker/
│  │  ├─ main.py         # entrypoint, dispatch handling
│  │  ├─ maria_agent.py  # Agent subclass, prompt assembly, tools
│  │  ├─ amd_flow.py
│  │  ├─ postcall.py     # analysis + upload
│  │  ├─ crm_client.py
│  │  └─ Dockerfile
│  └─ web/src/crm/       # pages: Dashboard, Campaigns, Leads, Calls, Appointments, Review, Playbooks, Settings
├─ packages/
│  ├─ playbook-schema/   # pydantic + json schema + examples/
│  └─ shared/
├─ docs/outbound/        # these documents
└─ scripts/              # lk_setup.sh, test_call.py, import_csv.py, taglish_stt_eval.py
```

## 6. Environment variables

**api / worker-jobs**
```
DATABASE_URL, REDIS_URL (optional)
ANTHROPIC_API_KEY, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY
LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
LIVEKIT_AGENT_NAME=maria-outbound
S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY
INTERNAL_API_SECRET           # shared with voice-worker
EMAIL_PROVIDER=resend, RESEND_API_KEY, FROM_EMAIL
SMS_PROVIDER=telnyx, TELNYX_API_KEY, TELNYX_MESSAGING_PROFILE_ID
OMNICX_BASE_URL, OMNICX_API_KEY (optional)
OPENLEADS_BASE_URL, OPENLEADS_API_KEY (optional)
MAX_CONCURRENT_CALLS=10
DEFAULT_RECORDING_RETENTION_DAYS=180
JWT_SECRET
```
**voice-worker**
```
LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_AGENT_NAME
ANTHROPIC_API_KEY, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY
API_BASE_URL, INTERNAL_API_SECRET
S3_* (for direct upload if not using egress)
```
Trunks and caller IDs are **data** (table `sip_trunks`), not env vars, so US and PH trunks coexist.

## 7. LiveKit setup (Phase 0/2, via `lk` CLI — script `scripts/lk_setup.sh`)

1. `lk sip outbound create telnyx-us.json` — address `sip.telnyx.com`, numbers `[+1XXXXXXXXXX]`, auth username/password from the Telnyx SIP connection.
2. Store returned trunk id in `sip_trunks` (market=US).
3. Test: `lk dispatch create --new-room --agent-name maria-outbound --metadata '{"phone":"+1...","test":true,...}'`.
4. PH: second outbound trunk pointing at your Asterisk/PH provider; `sip_number` = PH caller ID.

## 8. Security
- `internal/*` routes require `X-Internal-Secret`; everything else JWT + role.
- Recording URLs signed, 15-min expiry.
- Audit table for DNC, appointment changes, playbook version activation.
- Rate-limit public webhooks; verify signatures on inbound webhooks (LiveKit egress, Telnyx).

## 9. Observability
- Structured JSON logs with `attempt_id`, `campaign_id`.
- Per-call metrics table: `stt_seconds, tts_chars, llm_input_tokens, llm_output_tokens, telephony_seconds, latency_p50/p95, cost_usd`.
- `/health` on every service; Railway alerts on restarts.
