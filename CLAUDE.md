# maria-agent

Monorepo for Maria, Altria's AI voice agent. First module: **Maria Outbound** — appointment-setting
calls for any campaign + a mini CRM. Design docs live in docs/outbound/.

## Outbound appointment-setting module (Maria Outbound)

Read docs/outbound/00-MASTER-PLAN.md and 02-ARCHITECTURE.md before touching
apps/api/app/{crm,dialer,learning,notify,internal}, apps/voice-worker, apps/web/src/crm
or packages/playbook-schema. docs/outbound/06-CLAUDE-CODE-PHASE-PROMPTS.md defines the phase order.

### Non-negotiable rules
- Campaign-specific behaviour lives ONLY in playbook JSON (packages/playbook-schema). Never add
  `if campaign == ...` code.
- Secrets only from environment variables (Railway). Never commit keys, never print them in logs.
- Trunks and caller IDs are rows in `sip_trunks`, not env vars.
- Routes under /internal/* require header X-Internal-Secret. Everything else uses JWT + roles.
- While campaign.test_mode is true, dial ONLY numbers in campaign.test_allowlist. Enforce in the
  scheduler AND in the test-call endpoint.
- Never auto-activate a playbook version. Activation is a human action (audit-logged), gated by
  eval pass rate for non-test campaigns.
- Maria is an AI and says so when asked (compliance.ai_disclosure_text). Never make her claim to
  be human. Never let her state facts outside playbook.facts.
- Opt-out phrases → add_to_dnc immediately, then farewell, then end_call.
- A lead must never be dialed twice concurrently (FOR UPDATE SKIP LOCKED) and must never stay in
  `calling` for more than 15 minutes (watchdog).
- Prospect PII in training transcripts is redacted. No voice cloning. No fine-tuning jobs.

### Stack
FastAPI + SQLAlchemy 2 + Alembic + Postgres/pgvector (apps/api) · Python livekit-agents worker
with Deepgram nova-3 / Anthropic / ElevenLabs flash v2.5 / Silero VAD (apps/voice-worker) ·
Vite+React+Tailwind (apps/web) · LiveKit Cloud (rooms, SIP, egress) · Telnyx (US/CA trunk),
PH trunk TBD · S3-compatible bucket for recordings · Railway for all deployments.

### Conventions
- Migrations: one Alembic revision per phase, descriptive names.
- Tests: pytest in apps/api/tests and apps/voice-worker/tests; run `make test` before claiming done.
- Money in numeric(12,4) USD; phone numbers E.164 strings; times timestamptz; prospect-local
  rendering uses leads.timezone.
- Structured JSON logs with attempt_id and campaign_id on every line in the call path.
- Keep the "Current state" section below updated at the end of every session.
- Developer is on Windows (PowerShell); give commands that work there.

### Current state
(Claude Code updates this: phase completed, what works, known gaps, next step.)
- 2026-09-28: repo created. Only CLAUDE.md and docs/outbound/ exist. Next: Phase 0.5 scaffold.
- 2026-09-29: **Phase 0.5 (scaffold) done.**
  - Works: uv workspace (root pyproject.toml + uv.lock) with apps/api, packages/shared
    (`maria_shared`), packages/playbook-schema (`playbook_schema`). apps/api: FastAPI `/health` →
    {"ok":true}, pydantic-settings for all 02 §6 env vars (secrets are SecretStr), JSON logging with
    `log_context(attempt_id=..., campaign_id=...)`, async SQLAlchemy engine + Base, Alembic revision
    `0001_phase0_5` (pgvector + pgcrypto). Empty module packages crm/dialer/learning/notify/internal.
    apps/web: Vite + React 19 + TS + Tailwind v4 + TanStack Query + React Router 7, sidebar shell with
    placeholder /crm/* pages and an API health dot. Makefile + scripts/*.ps1 equivalents,
    docker-compose (pgvector/pgvector:pg16), Dockerfiles + railway.json for api (context = repo root,
    pre-deploy `alembic upgrade head`) and web (nginx, SPA fallback, `VITE_API_BASE_URL` build arg),
    GitHub Actions CI (ruff, pytest with pgvector service, alembic round-trip, eslint/tsc, vitest, build).
  - Tests: pytest creates/drops `<db>_test` (or uses TEST_DATABASE_URL), migrates to head; per-test
    session rolled back. `make test` / `make lint` pass (8 pytest + 1 vitest).
  - Known gaps: docker compose and the Dockerfiles have not been run (no Docker daemon in the build
    sandbox; checked against a local Postgres 16 + pgvector). The PowerShell scripts have not
    been run on Windows. Nothing is deployed to Railway yet.
  - Next: Phase 1 (CRM foundation), per 06-CLAUDE-CODE-PHASE-PROMPTS.md.
- 2026-09-29: **Phase 1 (CRM foundation) done.**
  - Decisions recorded under "Clarifications" at the top of 03-CRM-DATA-MODEL.md: 03 lead statuses
    are canonical (callback_due/retry_due are scheduler *conditions*), campaigns.requeue_no_show,
    and a watchdog for both attempts and leads.
  - Schema: Alembic `0002_phase1` creates all 25 tables from 03 §1 (16 Postgres enums, listed
    indexes, ivfflat on objection_library.embedding, NULLS NOT DISTINCT unique on dnc_entries). The
    circular FKs are added after the tables. Upgrade, downgrade and upgrade all work, and
    `alembic check` is clean. Models are in app/crm/models.py and app/learning/models.py.
  - API `/api/v1` (app/crm/routers): auth (bcrypt + HS256 JWT; role/is_active re-read from the DB
    on every request), /me, users, clients, campaigns (CRUD, actions
    start/pause/resume/complete/clone, playbook versions + activate with the ≥90 % eval gate for
    non-test campaigns and an audit-logged admin override), leads (CSV import with dry_run
    preview, list/search/filter, manual create, PATCH, timeline, bulk requeue/move/dnc/export),
    DNC (add also moves matching leads to `dnc`, check, admin-only delete), teams + availability,
    and sip-trunks. Roles: admin all; manager writes campaigns/leads/teams/DNC; rep/qa read-only
    except DNC add. Changes to users, trunks, campaigns, DNC, leads and playbook activation are
    audit-logged.
  - packages/shared: normalize_phone (E.164, phonenumbers, region default = row country →
    campaign.country_codes[0] → market) and infer_timezone (US state / CA province → phone area
    code → PH=Asia/Manila → campaign default).
  - dialer/state_machine.py: pure `transition()` for the 03 §2 table plus the watchdog rule
    (first stale attempt → queued, a repeat → exhausted). Deviations: callback leads are pickable
    (Clarification 1); no_human/failed/hung_up_early retry like no_answer; manual requeue is
    refused for dnc and calling leads; attempts are counted when the outcome is recorded.
  - Web: login (JWT in localStorage, 401 → logout), Campaigns (list + 6-tab editor, test-mode
    banner, start/pause/resume/clone/complete, JSON-textarea playbook versions), Leads (4-step
    import wizard, TanStack Table with timezone + local time, bulk bar, lead drawer), Settings
    (users/teams/DNC/SIP trunks).
  - Seed: `scripts/seed.ps1` (app/seed.py, idempotent; admin password from SEED_ADMIN_PASSWORD).
    `scripts/sample_leads.csv`: 50 rows US/CA/PH → import 45 / 3 dupes / 2 DNC / 0 invalid.
  - Tests: 118 pytest (state machine, phone/timezone, auth + role matrix, import incl. dupes/DNC/
    bad phones, campaigns/playbooks/bulk/DNC, sample CSV) + 4 vitest. The browser walkthrough
    (log in, create campaign, import sample, check timezones) passed on a local Postgres 16.
  - Known gaps: not run on Windows or against Railway Postgres here. No client scoping of data
    for users with client_id (NFR-7 later). No login rate limiting. Playbook JSON is only checked
    to be an object (schema validation is Phase 2). The availability API exists, but has no UI yet.
    Dashboard/Calls/Appointments/Review/Playbooks pages are placeholders. OpenLeads import and
    API keys are not built.
  - Next: Phase 2 (first AI call), per 06-CLAUDE-CODE-PHASE-PROMPTS.md.
- 2026-10-01: **Phase 2a (first AI call, trimmed Phase 2) built; live call not yet run.**
  - packages/playbook-schema: Pydantic models for 04 §1 + §4 `runtime` (extra keys forbidden),
    04 §7 rules (placeholders, regex triggers, opener ≤ 60 words, required dispositions, onsite ⇒
    address, disclosure text), `validation_errors()`, `playbook.schema.json` (regenerate with
    `uv run python -m playbook_schema`; a test fails if it is stale), `examples/yp_seo_us.json`, and
    `prompt.py::build_system_prompt` (04 §2 order). The prompt has a snapshot test; regenerate it
    with UPDATE_SNAPSHOTS=1.
  - API: `/internal/*` (X-Internal-Secret, constant-time compare, 503 if unset).
    - `GET dispatch-context`: re-checks the test allowlist and the playbook.
    - `PATCH calls/{id}`: the first `outcome` finishes the attempt and applies the state machine
      once (app/dialer/calls.py).
    - `POST events`: atomic append to `transcript` for turns, `call_events` for everything else.
    - `POST tool/{name}`: all of 03 §4, idempotent per attempt, every call logged as a `tool`
      call_event. send_info / transfer_to_human / escalate_complaint are stubs returning
      `{allowed:false}`; escalate also sets needs_review.
    - Tools only set `attempt.disposition` (precedence dnc > appointment_set > wrong_number >
      callback > not_interested > rest). The lead status changes once, at the final PATCH.
      add_to_dnc writes the DNC entry and an opt_out consent event immediately.
    - check_slots is static: Mon–Fri 10:00/14:00 in the prospect's timezone, respecting
      min_lead_time/max_days_ahead (app/dialer/slots.py). book_appointment only accepts those slots.
      schedule_callback parses ISO or simple phrases and clamps to 08:00–21:00.
  - API, test calls:
    - `POST /campaigns/{id}/test-call` (manager+) refuses unless the campaign is in test_mode, the
      phone is on test_allowlist and not on the DNC list, there is an active trunk with a LiveKit
      id, a caller_id and a valid active playbook, and the lead isn't calling. It takes a row lock,
      does ManualRequeue → SchedulerPick, creates the attempt, commits, then dispatches
      (dialer/livekit_client.py, a FastAPI dependency). If the dispatch fails, the attempt is
      marked failed and the lead goes back to queued.
    - `GET /calls/{id}` (JWT) for polling. `POST /campaigns/{id}/playbooks/validate`.
    - Saving a playbook version is still unvalidated; test-call and dispatch-context validate it.
  - apps/voice-worker (virtual uv workspace member, livekit-agents pinned ~=1.8.3): main.py
    (AgentServer, dispatch context → session.start → AMD helper wrapping create_sip_participant
    with wait_until_answered → human: greet unless a reply is already pending; machine:
    voicemail/ivr/no_human), maria_agent.py (11 tools; set_stage/end_call don't trigger a reply;
    end_call hangs up after the farewell plays), amd_flow.py (SIP status / AMD mapping),
    postcall.py (`messages.parse` structured output → 04 §6 result; latency p50/p95 from
    `e2e_latency`), crm_client.py (retries 5xx only). End conditions: end_call, prospect hangup,
    max_duration, silence (user_away_timeout: one "still there?", then farewell). A shutdown hook
    marks unfinished attempts failed.
  - Models: live `claude-sonnet-4-6`, because the livekit Anthropic plugin drops thinking blocks
    and Sonnet 5.5 can't run without them. Analysis `claude-sonnet-5-5` via the SDK; AMD
    `claude-haiku-4-5`.
  - Scripts: lk_setup.py/.ps1 (appends INTERNAL_API_SECRET to .env if missing; creates or syncs
    the LiveKit trunk "telnyx-us"; upserts the sip_trunks row, campaign, active playbook version
    and test lead; audit-logged), worker.ps1 (download-files, then dev), test_call.py/.ps1.
  - Tests: 188 pytest (playbook rules + snapshot, slots/callbacks, internal auth, every tool,
    events, PATCH idempotency + state application, test-call guards incl. allowlist/test_mode/DNC/
    concurrent/dispatch failure, lk_setup idempotency, worker helpers and tool schemas).
    test_call.py was run end to end against the API with a fake dispatcher that plays a scripted
    call through the real internal endpoints.
  - Known gaps:
    - Never run against LiveKit, Telnyx, Deepgram, ElevenLabs or Anthropic: there were no
      credentials, and huggingface.co is blocked in the build sandbox, so `download-files` was
      untested. The worker's live path (AMD timing, greeting, hangup) needs the acceptance call.
    - The turn-detector plugin is deprecated in 1.8.3 (warning only).
    - No recording/egress, Calls UI or voice-worker Dockerfile (Phase 2b).
    - No confirmation SMS/email.
    - The cost_usd/usage roll-up is not computed.
    - Not run on Windows.
  - Next: acceptance call with the developer (lk_setup → dev → worker → test_call), then
    Phase 2b (recording/egress, Calls page, worker Dockerfile).
