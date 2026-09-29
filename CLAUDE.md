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
