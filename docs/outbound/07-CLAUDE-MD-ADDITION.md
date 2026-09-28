# 07 — Repo `CLAUDE.md` content

The repo's root `CLAUDE.md` was created from this text on 2026-09-28. If it ever gets lost, recreate it from the block below. Claude Code keeps the "Current state" section updated.

```markdown
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
```
