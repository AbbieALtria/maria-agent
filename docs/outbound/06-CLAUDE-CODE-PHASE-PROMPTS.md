# 06 — Claude Code Phase Prompts

How to use: open Claude Code in the `maria-agent` repo, paste one prompt, let it **plan first**, review the plan, then let it implement. Commit when the acceptance criteria pass. Start each new session with the "Session opener" so context is loaded.

The repo is brand new (only `CLAUDE.md` and `docs/outbound/` exist at the start). Run **Phase 0.5** first.

---

## Session opener (paste at the start of every session)

```
Read CLAUDE.md and docs/outbound/00-MASTER-PLAN.md, 02-ARCHITECTURE.md and 03-CRM-DATA-MODEL.md.
Summarize in 10 lines the current state of the outbound module (what exists in apps/api/app/crm,
apps/api/app/dialer, apps/voice-worker, apps/web/src/crm, packages/playbook-schema) and what the
next phase requires. Do not write code yet.
```

---

## Phase 0.5 — Scaffold the monorepo

```
This repo is empty except for CLAUDE.md and docs/outbound/. Scaffold the monorepo exactly per
docs/outbound/02-ARCHITECTURE.md §5. Plan first, then implement:

1. apps/api: FastAPI app (Python 3.11, uv or pip-tools, pyproject.toml), SQLAlchemy 2.0 async,
   Alembic initialised (empty first revision enabling pgvector + pgcrypto), pydantic-settings
   config reading the env vars in 02 §6, /health endpoint, structured JSON logging, pytest setup
   with a test database fixture.
2. apps/web: Vite + React + TypeScript + Tailwind + TanStack Query + React Router; an app shell
   with sidebar and a placeholder /crm route; .env.example with VITE_API_BASE_URL.
3. packages/playbook-schema and packages/shared as installable Python packages (empty modules
   + tests folder) that apps/api and the future apps/voice-worker can import.
4. Root: Makefile (make dev = api + web concurrently, make test, make lint, make migrate),
   docker-compose.yml with Postgres 16 + pgvector for local dev, .env.example, .gitignore
   (Python, Node, .env, recordings), README.md with setup steps for Windows (PowerShell).
5. Railway: railway.json / Dockerfiles for api and web so each deploys as its own service;
   do not deploy yet.
6. GitHub Actions: lint + test on push.

Acceptance: `docker compose up -d` starts Postgres; `make dev` serves GET /health → {"ok":true}
and the web shell at http://localhost:5173/crm; `make test` passes; first commit made.
Update the "Current state" section in CLAUDE.md.
```

## Phase 1 — CRM foundation

```
Implement Phase 1 (CRM foundation) exactly as specified in docs/outbound/03-CRM-DATA-MODEL.md
and the requirements in 01-REQUIREMENTS.md §2.1–2.2, §2.6 (screens 2 and 3 only), §2.6 FR-U7.

Plan first, then implement:
1. Alembic migration creating ALL tables in 03 §1 (create them now even if unused, so later
   phases don't churn migrations). Enums as Postgres enums. Indexes as listed.
2. SQLAlchemy 2.0 models + Pydantic schemas in apps/api/app/crm/.
3. Routers: auth, campaigns (+ actions, clone), leads (CSV import with column mapping, dedupe
   by E.164 within campaign, DNC skip, import report), lead bulk actions, dnc, users, teams,
   sip_trunks. Auth = email+password + JWT with roles (admin, manager, rep, qa).
4. packages/shared: phone normalization to E.164 (phonenumbers lib) with country default from
   campaign; timezone inference from phone region / US state / PH default Asia/Manila.
5. React CRM shell at /crm with sidebar; pages: Campaigns (list/create/edit with tabs from
   03 §5.2, playbook tab can be a plain JSON textarea for now), Leads (import wizard + table +
   lead drawer), Settings (users, teams, DNC, SIP trunks).
6. Seed script: admin user, one client "YP", one campaign "YP SEO US (test)" in test_mode,
   one sip_trunk placeholder.
7. Tests: pytest for import (dupes, DNC, bad phones), state machine transitions (implement
   dialer/state_machine.py now with the table from 03 §2), auth/roles.

Acceptance: `make dev` runs api+web; I can log in, create a campaign, import scripts/sample_leads.csv
(create it, 50 rows, mixed US/CA/PH, 3 duplicates, 2 DNC), see the import report and the leads
table with correct timezones. All tests pass. Update CLAUDE.md "Current state" section.
```

## Phase 2 — First AI call

```
Implement Phase 2 (first AI call) per docs/outbound/02-ARCHITECTURE.md §2–3, §7 and
04-CAMPAIGN-PLAYBOOK-SPEC.md.

1. packages/playbook-schema: Pydantic models for the playbook JSON (04 §1, §4) + JSON Schema
   export + validation rules (04 §7) + examples/yp_seo_us.json (copy the example from 04 §1,
   fill placeholders sensibly). Unit tests for validation.
2. apps/voice-worker: Python 3.11 project with livekit-agents and plugins deepgram, anthropic,
   elevenlabs, silero, turn-detector. Files per 02 §5. Entrypoint reads ctx.job.metadata
   {attempt_id, phone, trunk_id, caller_id, campaign_id, playbook_version_id, test}. It fetches
   /internal/dispatch-context/{attempt_id}, creates the SIP participant with
   wait_until_answered=True, handles SipCallError → PATCH attempt failed with sip_status, then
   runs AMD (livekit AMD helper; if unavailable in the installed version, implement the
   amd.py-style approach: listen to the first ~4 s of transcript, classify human vs machine with
   the Haiku-class model). On human: MariaAgent from playbook (prompt assembly per 04 §2),
   tools per 03 §4 forwarding to /internal/calls/{id}/tool/{name}. Stream transcript turns to
   /internal/calls/{id}/events. On end: post-call analysis (04 §6) → PATCH result.
3. apps/api: internal router (X-Internal-Secret): dispatch-context, PATCH calls, events, tool
   endpoints (implement check_slots with static availability_rules, book_appointment,
   schedule_callback, mark_*, add_to_dnc, set_stage, end_call; stub send_info/transfer/escalate
   returning {allowed:false}). dialer/livekit_client.py wrapping CreateAgentDispatch.
   Endpoint POST /campaigns/{id}/test-call {lead_id} that creates a call_attempt and dispatches
   (only allowed when campaign.test_mode and phone in test_allowlist).
4. Recording: LiveKit egress audio-only to S3 bucket, started when human detected; webhook
   /webhooks/livekit stores recording_url. If egress is not available in the account tier,
   fall back to worker-side recording of the mixed audio and upload to S3.
5. scripts/lk_setup.sh (create outbound trunk from telnyx-us.json template, print trunk id) and
   scripts/test_call.py (CLI wrapper around the test-call endpoint).
6. Railway: Dockerfile for voice-worker; document required variables in README; do not deploy
   until I confirm.
7. Web: Calls page (table + detail with transcript, result JSON, audio player using signed URL).

Acceptance: with LIVEKIT_* and trunk configured, `python scripts/test_call.py --lead <id>` makes my
phone ring; Maria greets me after I say hello, follows the YP SEO playbook, books an appointment
when I agree, says goodbye and hangs up; the call appears in /crm/calls with transcript, result,
recording, and the appointment appears in the DB. Latency logs show p50 response < 1.2 s.
```

## Phase 3 — Campaign engine

```
Implement Phase 3 (campaign engine) per 01-REQUIREMENTS.md §2.3, 02-ARCHITECTURE.md §2 step 1 and §4.

1. dialer/scheduler.py: tick every 10 s (APScheduler in worker-jobs process, single instance);
   lead selection SQL with FOR UPDATE SKIP LOCKED honoring: campaign active, calling_window in
   lead timezone, daily_cap, daily_budget_usd, concurrency (count of attempts in dialing/in_call),
   global MAX_CONCURRENT_CALLS, DNC check, next_attempt_at, test_mode allow-list.
2. Retry policy (max_attempts, retry_spacing_hours, spread_time_of_day, voicemail_counts_as_attempt),
   callback handling, watchdog for stale attempts (15 min), pause/resume/kill-switch
   (campaign action + global setting), voicemail message playback and IVR DTMF per playbook.
3. Post-call state application in one transaction: lead status, attempts, next_attempt_at,
   appointment link, cost roll-up (metrics jsonb → cost_usd using a rates table in settings).
4. Web: Dashboard (KPI tiles, funnel, hourly heatmap, live calls), Review queue, campaign
   Start/Pause/Kill, Playbooks page with Monaco JSON editor + schema validation + version
   activate + Simulate panel (POST /campaigns/{id}/simulate — text chat against the same prompt
   assembly and tools, no telephony).
5. Tests: scheduler selection edge cases (window boundaries across DST, cap reached, concurrency),
   retry math, watchdog.

Acceptance: a test campaign with 20 leads (all my allow-listed numbers, some I let ring, one to
voicemail) runs unattended to completion; every lead ends in a terminal or scheduled state;
dashboard numbers match the DB; no lead stuck in `calling`.
```

## Phase 4 — Appointments & handoff

```
Implement Phase 4 per 01-REQUIREMENTS.md §2.5 and 03 §3 (appointments, teams/slots, notifications).

1. Slot engine: availability_rules + overrides + existing appointments + buffer + min_lead_time
   → GET /teams/{id}/slots; check_slots tool returns 2–4 slots phrased in prospect-local time
   ("Thursday at ten in the morning"). Handle prospect vs team timezone.
2. Appointment actions (confirm/cancel/reschedule/complete/no_show), ICS generation,
   appointment_events, requeue on no_show if campaign flag.
3. notify/: provider interfaces for email (Resend) and SMS (Telnyx; adapter interface so a PH
   SMS gateway can be added), templates per campaign (Jinja), team notifications (email +
   webhook payload), reminders job (24 h / 2 h), inbound SMS webhook (STOP → dnc).
4. Webhooks out (appointment.created/updated, call.completed) with HMAC signature and retries.
5. Web: Appointments calendar (week/day) + list + detail drawer; rep role sees own; Teams &
   availability editor in Settings.
6. Optional if time: Google Calendar free/busy for reps (OAuth) behind a feature flag.

Acceptance: Maria books an appointment in a test call → prospect (me) receives SMS+email with
ICS; team gets email+webhook; appointment visible in calendar; reschedule from UI sends updated
notification; reminders fire in a time-accelerated test.
```

## Phase 5 — Learning from recordings

```
Implement Phase 5 per docs/outbound/05-RECORDING-LEARNING-PIPELINE.md.

1. learning/: upload endpoint (multipart, to S3), Deepgram batch transcription job (diarize,
   multichannel when stereo, redaction), speaker labeling, per-call analysis, corpus synthesis,
   playbook draft generation validated against packages/playbook-schema, eval scenario generation.
2. Simulation harness: learning/evals/run — Claude plays each persona in text against the live
   prompt assembly + tools (mock tool backend), grader scores pass/fail; store eval_runs.
   Activation gate for non-test campaigns (≥90 % pass + all compliance scenarios) with admin
   override + audit log.
3. objection_library with pgvector embeddings; nightly clustering job from failed objections and
   QA corrections; "Suggest playbook update" → draft version + diff.
4. Web: Learning page (upload, run analysis, report viewer, create draft, run evals, results
   table, objection library).
5. Create repo skill .claude/skills/playbook-author/SKILL.md describing how to turn an analysis
   report into a valid playbook and how to run evals.

Acceptance: upload 10 sample recordings (I will provide) → analysis report → playbook draft passes
schema → 20 eval scenarios run and results display; activation blocked when pass rate < 90 %.
```

## Phase 6 — YP SEO pilot readiness

```
Prepare the YP SEO pilot: security/ops hardening and go-live checklist.
- Rate limits, signed recording URLs, retention job, audit log coverage, RBAC tests.
- Structured logging + per-call cost metrics; /health endpoints; Railway deploy of api,
  worker-jobs, voice-worker, web using the Railway MCP; staging vs production env.
- Load test: 10 concurrent simulated calls against the worker (text-mode + a few real).
- Go-live checklist in docs/outbound/GO-LIVE.md: trunk verified, caller ID inbound handling
  (voicemail or IVR message logging callbacks), DNC scrub done, calling windows set, playbook
  version passed evals, kill-switch tested, budget cap set.
```

## Phase 7 — PH / Taglish gate

```
Implement scripts/taglish_stt_eval.py per 05 §4 with a pluggable STT interface (Deepgram tl /
multi / en, plus one alternative provider behind an interface). Produce a report (WER, key-info
accuracy) and a listening review CSV. Then add the second sip_trunk (PH) support end-to-end,
create telecom_ph.json and cleaning_ph.json example playbooks per 04 §5.2–5.3, and test-call my
PH number. Do not enable PH campaigns until I review the report.
```

## Phase 8 — Integrations

```
Implement: GET /public/stats for The Bridge (API key, per-campaign funnel, appointments, cost);
OpenLeads push endpoint POST /public/leads (map OpenLeads fields into leads.custom); OmniCX
escalation in escalate_complaint tool (ingestTicketEvent payload); optional ViciDial disposition
sync adapter (feature flag) mapping playbook dispositions to ViciDial status codes via
ops.altriacallcenter.com API. Document all payloads in docs/outbound/INTEGRATIONS.md.
```

---

## Guardrail prompt (paste whenever Claude Code drifts)

```
Stop. Re-read docs/outbound/02-ARCHITECTURE.md and 04-CAMPAIGN-PLAYBOOK-SPEC.md. Rules:
no campaign-specific code paths; everything campaign-specific lives in the playbook JSON;
secrets only via environment; internal routes require X-Internal-Secret; never auto-activate
playbooks; never dial outside test_allowlist while test_mode=true. Show me the plan before
changing more than 3 files.
```
