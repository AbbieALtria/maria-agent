# Maria Outbound — Master Plan

**Project:** Maria Outbound Appointment-Setting Agent + Mini CRM
**Repo:** `AbbieALtria/maria-agent` (new monorepo — created 2026-09-28; the earlier Maria QR/chat prototype was never pushed, so this repo starts from scratch and is scaffolded in Phase 0.5)
**Owner:** Abuyahya / Altria Support Services
**Date:** 2026-09-28
**Status:** Design approved — ready for Claude Code implementation

---

## 1. What we are building

Maria calls a list of leads on behalf of any campaign, holds a natural human-like
conversation (English for US/CA, English/Taglish for PH), qualifies the prospect,
and books an appointment for a human sales team. Every call, disposition and
appointment lands in a small CRM that the sales team and management use.

Three launch campaigns prove the model is generic:

| Campaign | Market | Who visits/follows up | Appointment type |
|---|---|---|---|
| YP SEO (SEO services for local businesses) | US / Canada, English | SEO team (phone/Zoom) | Phone or Zoom consult, 15–30 min |
| Telecom services | Philippines, English/Taglish | Field sales team | On-site visit |
| Cleaning services | Philippines, English/Taglish | Ops/estimator | On-site estimate |

Anything else (insurance, solar, HVAC, etc.) is a new **campaign playbook** JSON —
no code change.

## 2. Decisions locked in

| Topic | Decision | Why |
|---|---|---|
| Telephony | **Own pipeline: LiveKit Agents + SIP trunk** (Telnyx for US/CA; PH termination via your existing ViciDial/Asterisk trunks or a PH SIP provider) | Full control, lowest per-minute cost, you own recordings/data, one engine for both markets |
| Voice-AI hosting | LiveKit **Cloud** for the media/SIP layer; Maria worker + API + CRM on **Railway** | Self-hosting SIP/RTP (UDP) on Railway is not practical; LiveKit Cloud gives SIP trunks, dispatch, AMD and recording out of the box |
| STT | Deepgram Nova-3 (`en` for US/CA; `tl` / multilingual for PH, gated by an accuracy test) | Nova-3 lists Tagalog; Taglish quality must be measured before PH go-live |
| LLM | Claude (Sonnet-class for live turns, Haiku-class for AMD/classification, Opus/Sonnet for post-call analysis and recording learning) | Reasoning layer for Maria |
| TTS | ElevenLabs Flash v2.5 (supports Filipino; ~75 ms) | Low latency, Filipino support |
| CRM | **New standalone CRM module** in the monorepo, own Postgres schema, REST API, React UI | Sales team needs a clean appointment/disposition view; exposes an API so The Bridge can report on it |
| Codebase | **New `maria-agent` monorepo** (layout in `02-ARCHITECTURE.md` §5), built so the inbound QR voice+chat Maria can be added later as another app | One engine, per-campaign JSON config |
| Lead sources | CSV upload, OpenLeads API, (later) ViciDial list export | Matches what you already have |
| ViciDial | Optional, not in the critical path. Dispositions can be pushed to ViciDial-connected `ops.altriacallcenter.com` later if needed | You decided earlier to keep Maria independent of ViciDial |

## 3. Stack summary

```
Prospect phone  ⇄  Carrier (Telnyx / PH trunk)  ⇄  LiveKit Cloud SIP  ⇄  LiveKit Room
                                                                            ⇅
                                              apps/voice-worker (Python, LiveKit Agents)
                                              Deepgram STT → Claude → ElevenLabs TTS
                                                                            ⇅ REST/webhooks
apps/api (FastAPI)  ── Postgres+pgvector ──  apps/web (React/Vite)  ── The Bridge / OmniCX
   ├─ crm module (campaigns, leads, calls, appointments)
   ├─ dialer module (queue, pacing, calling windows, retries, DNC)
   ├─ learning module (recording ingest → playbook drafts → eval sets)
   └─ notifications (email/SMS confirmations, sales-team alerts)
```

All services deploy on Railway (existing project). Object storage for recordings:
Railway bucket (S3-compatible) or Cloudflare R2.

## 4. Documents in this set

| File | Purpose | Give to Claude Code when… |
|---|---|---|
| `00-MASTER-PLAN.md` | This file — decisions, phases, accounts | Always in `docs/` |
| `01-REQUIREMENTS.md` | Functional & non-functional requirements, compliance | Phase 1 onward |
| `02-ARCHITECTURE.md` | Services, call flow, repo layout, env vars, Railway services | Phase 1 onward |
| `03-CRM-DATA-MODEL.md` | Postgres schema, API, UI screens | Phase 1 |
| `04-CAMPAIGN-PLAYBOOK-SPEC.md` | Campaign JSON schema, Maria's tools, prompt assembly, 3 example playbooks | Phase 3 |
| `05-RECORDING-LEARNING-PIPELINE.md` | How Maria learns from your human agents' recordings | Phase 5 |
| `06-CLAUDE-CODE-PHASE-PROMPTS.md` | Copy-paste prompts, one per phase, with acceptance criteria | Every session |
| `07-CLAUDE-MD-ADDITION.md` | Text to append to the repo's `CLAUDE.md` | Phase 1, first thing |

Put all of them in `maria-agent/docs/outbound/`. Claude Code reads them by path.

## 5. Phases (each is one or more Claude Code sessions)

| Phase | Deliverable | Exit test |
|---|---|---|
| **0 – Accounts & trunk** (you, not Claude Code) | LiveKit Cloud project, Telnyx account + 1 US number, SIP outbound trunk configured in LiveKit, Deepgram/ElevenLabs/Anthropic keys in Railway | `lk sip outbound list` shows the trunk |
| **0.5 – Scaffold** | Empty monorepo per `02` §5: apps/api (FastAPI), apps/web (Vite+React), packages/, Makefile, docker-compose for Postgres+pgvector, CI lint/test | `make dev` serves API `/health` and the web shell |
| **1 – CRM foundation** | Schema + migrations, REST API, React CRM (campaigns, lead import, lead list, manual disposition) | Import a CSV of 50 leads, see them in UI |
| **2 – First AI call** | `apps/voice-worker` dials ONE number from CLI with a hard-coded English playbook, talks, hangs up, stores transcript + recording in CRM | Maria calls your phone and books a fake appointment |
| **3 – Campaign engine** | Playbook JSON loader, dialer queue/pacing/calling windows/retries/DNC, AMD, post-call structured disposition, appointment tools | 20-lead test campaign runs unattended, all calls dispositioned |
| **4 – Appointments & handoff** | Slot management, confirmations (email/SMS), sales-team notifications, human review queue, calendar export/ICS, optional Google Calendar | Sales team receives a booked appointment with recording link |
| **5 – Learning from recordings** | Upload human-agent recordings → transcripts → extracted playbook draft, objection library, FAQ, eval scenarios, simulation harness | Playbook for YP SEO generated from your recordings and passes 20 simulated calls |
| **6 – YP SEO pilot** | Live pilot, 200 leads, dashboards, tuning loop | ≥ X appointments/100 connects (set target after week 1) |
| **7 – PH / Taglish gate** | STT accuracy test on Taglish samples; if pass → telecom + cleaning campaigns; if fail → evaluate alternative STT | WER on 30 Taglish clips acceptable to you |
| **8 – Integrations** | The Bridge reporting endpoint, OmniCX escalation on complaints, optional ViciDial disposition sync | Bridge shows appointments per campaign |

## 6. Accounts, connectors and skills you need

### Accounts (Phase 0 — you set these up)
- **LiveKit Cloud** — project, API key/secret, SIP outbound trunk. Start on the free/dev tier.
- **Telnyx** — buy 1 US local number (caller ID for YP SEO), create SIP connection (credential auth), point LiveKit outbound trunk to `sip.telnyx.com`. Canada: add a CA number later.
- **PH termination** — two options, test both: (a) LiveKit outbound trunk → your ViciBox Asterisk (needs a public SIP reachability path + registration/IP auth) using your existing PH carrier trunks and PH caller IDs; (b) a PH-capable SIP provider. Decide in Phase 7.
- **Deepgram, ElevenLabs, Anthropic** — already have. Keys live in Railway variables only.
- **Object storage** for recordings — Railway bucket or Cloudflare R2.
- **Email/SMS** — Resend or Postmark for email; Telnyx Messaging (US) / existing SMS adapter in OmniCX (PH) for confirmations.

### Claude Code connectors / MCP
- **Railway MCP** — already connected; use it for deploy, logs, variables.
- **GitHub** — via `git` (install `gh` CLI optionally). Create the empty repo `AbbieALtria/maria-agent` on GitHub and push after the first commit.
- **LiveKit CLI (`lk`)** — install locally; Claude Code uses it for trunk/dispatch setup and test calls.
- No other connectors required. Do **not** give Claude Code the carrier or LiveKit web dashboards; keep those manual.

### Claude Code skills
- None mandatory. Optional: a small repo-local skill `.claude/skills/playbook-author/` that turns a recording-analysis report into a campaign JSON (created in Phase 5).
- The repo `CLAUDE.md` (see `07-CLAUDE-MD-ADDITION.md`) does most of the steering.

## 7. Cost picture (order of magnitude, verify current prices)

Per connected minute: STT ≈ $0.005–0.008, TTS ≈ $0.03–0.06 (Flash), LLM ≈ $0.01–0.03, LiveKit ≈ $0.004–0.01, carrier US ≈ $0.007–0.01, PH termination ≈ $0.02–0.05. Budget roughly **$0.08–0.15 per connected minute**, ~$0.30–0.50 per connected call. Non-connects (no answer, voicemail hang-up) cost cents. Check each vendor's current pricing page before the pilot.

## 8. Compliance guardrails (built in, per campaign flags)

- **US/CA:** B2B calls to business numbers are generally lower-risk than consumer calls, but respect calling windows (8am–9pm prospect local time), honor DNC/opt-out immediately, disclose recording where required, and set `ai_disclosure=true` — Maria says she is an AI assistant if asked and, where state law requires, up front. Scrub against the National DNC when calling any number that might be a consumer/sole proprietor. Never spoof caller ID; use your own registered numbers.
- **PH:** Data Privacy Act — lawful basis for calling, recording notice, opt-out honored. Reasonable calling hours.
- **All:** Maria never lies about being human when directly asked. Store consent/opt-out events in the CRM. Keep recordings encrypted at rest with a retention policy (default 180 days).

## 9. How to run this with Claude Code

1. `docs/outbound/` and `CLAUDE.md` are already in the repo; commit them.
2. Open Claude Code in the repo (`cd E:\maria-agent && claude`).
3. Paste the **Phase 0.5 (Scaffold)** prompt from `06-CLAUDE-CODE-PHASE-PROMPTS.md`, then Phase 1. Let it plan first (`/plan` or ask it to propose a plan before coding), review, then approve.
4. One phase per session (or two short sessions per phase). Commit at each exit test.
5. Report problems back here (Claude chat) for architectural changes; Claude Code does all code edits.
