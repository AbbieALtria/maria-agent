# 01 — Requirements (PRD)

## 1. Users

| User | Needs |
|---|---|
| **Campaign manager (Abuyahya / ops lead)** | Create campaign, upload leads, set calling windows and pacing, watch live stats, pause/resume, review flagged calls, edit playbook |
| **Sales rep / field agent** | See today's appointments, prospect details, call summary, listen to recording, confirm/reschedule/cancel, mark outcome (showed, sold, no-show) |
| **QA / trainer** | Listen to calls, grade Maria, tag objections she handled badly, feed corrections into the playbook |
| **Management (The Bridge)** | Per-campaign funnel: dials → connects → conversations → appointments → showed → sold |
| **Prospect** | A natural, respectful call; can say no, opt out, ask to be called later, or ask "is this a robot?" and get an honest answer |

## 2. Functional requirements

### 2.1 Campaigns
- FR-C1 Create/edit/archive campaign with: name, client, market (country, timezones), language(s), playbook (JSON), calling windows, max attempts, retry spacing, daily cap, concurrency, caller ID, appointment settings, compliance flags.
- FR-C2 Campaign statuses: draft → testing → active → paused → completed.
- FR-C3 "Test mode": only dials numbers in an allow-list (your own phones).
- FR-C4 Clone campaign.

### 2.2 Leads
- FR-L1 Import CSV (map columns in UI), import from OpenLeads API (by campaign/offer), manual add.
- FR-L2 Dedupe by normalized E.164 phone within a campaign; global DNC check on import and before every dial.
- FR-L3 Lead fields: business name, contact name, phone(s), email, address, city, state/province, country, timezone (derived from phone/address if missing), website, industry, source, custom JSON (e.g., review count, employee count from OpenLeads).
- FR-L4 Lead status machine: `new → queued → calling → contacted → appointment_set | callback | not_interested | wrong_number | dnc | exhausted | invalid`.
- FR-L5 Bulk actions: requeue, move to another campaign, mark DNC, export CSV.

### 2.3 Dialer
- FR-D1 Scheduler picks leads whose local time is inside the calling window, respects daily cap, concurrency limit (start at 2–3, config up to 20) and retry spacing (e.g., attempt 2 after ≥ 4 h, attempt 3 next day different time slot).
- FR-D2 Places call via LiveKit SIP; records SIP outcome (answered, busy, no-answer, failed, invalid number).
- FR-D3 Answering-machine detection: on voicemail either hang up or leave a configurable voicemail message; on IVR, optionally press configured DTMF (e.g., "0") once, else hang up and mark `ivr`.
- FR-D4 Maria starts speaking only after a human is detected.
- FR-D5 Hard call limits: max duration (default 8 min), silence timeout, max consecutive misunderstandings → polite exit.
- FR-D6 Pause/resume campaign instantly; kill-switch stops all new dials.
- FR-D7 Optional warm transfer to a human (SIP transfer to a ViciDial/agent extension) when playbook allows (`allow_transfer`).

### 2.4 Conversation (Maria)
- FR-M1 Human-like: natural opener, listens, handles interruptions (barge-in), backchannels, no robotic pauses > 1.2 s.
- FR-M2 Follows the campaign playbook: intro, permission, qualify, pitch, objections, close for appointment, confirm details, wrap-up.
- FR-M3 Tools Maria can call mid-conversation: `check_slots`, `book_appointment`, `schedule_callback`, `mark_not_interested`, `mark_wrong_number`, `add_to_dnc`, `transfer_to_human`, `send_info` (SMS/email), `end_call`.
- FR-M4 Honesty: if asked whether she is AI/robot, answers truthfully per campaign disclosure text. Never claims to be a specific human.
- FR-M5 Language: campaign default; can switch to Taglish/Tagalog if the prospect does (PH campaigns).
- FR-M6 Post-call: structured JSON — disposition, summary, qualification answers, objections raised, sentiment, next action, extracted fields (decision maker name, best time, email), confidence, `needs_review` flag.
- FR-M7 Every turn logged with timestamps and latency metrics.

### 2.5 Appointments
- FR-A1 Slot sources: (a) static weekly availability per campaign/team; (b) later: Google Calendar free/busy for named reps.
- FR-A2 Appointment fields: lead, campaign, assigned rep/team, type (call/zoom/onsite), start/end in prospect timezone and rep timezone, address for on-site, notes, status (`scheduled → confirmed → completed | no_show | cancelled | rescheduled`), outcome (`sold`, `follow_up`, `lost`), value.
- FR-A3 Confirmations: SMS and/or email to prospect (template per campaign); notification to rep (email + optional Slack/Telegram webhook); ICS attachment.
- FR-A4 Reminder job 24 h and 2 h before (configurable).
- FR-A5 Reschedule/cancel from CRM; optional Maria reminder call (later).

### 2.6 CRM UI
- FR-U1 Dashboard per campaign: dials, connects, human-answered, conversations > 30 s, appointments, appointment rate, avg call length, cost estimate, live calls now.
- FR-U2 Lead table with filters, search, status, attempts, last disposition.
- FR-U3 Call detail: audio player (recording), synced transcript, structured result, Maria's tool calls, QA grading form (1–5 + tags + free text).
- FR-U4 Appointments calendar (day/week) + list; rep view filtered to their appointments.
- FR-U5 Review queue: `needs_review` calls, low-confidence dispositions, complaints.
- FR-U6 Playbook editor: JSON editor with schema validation + "simulate a call" button (text chat with Maria in that playbook).
- FR-U7 Users/roles: admin, manager, rep, qa. Simple email/password auth + JWT (reuse existing auth if present).

### 2.7 Learning from recordings
- FR-R1 Upload human-agent recordings (mp3/wav) + optional outcome label (appointment / no).
- FR-R2 Batch transcription with diarization; store transcript.
- FR-R3 Analysis produces: playbook draft (opener, value props, qualifying questions, objection→rebuttal table, closing lines, FAQ), tone notes, forbidden phrases, and a set of simulated-prospect eval scenarios.
- FR-R4 Human approves the draft before it becomes the campaign playbook (versioned).
- FR-R5 Ongoing: Maria's own calls graded by QA feed an "objection library" that can be re-generated into playbook improvements.

### 2.8 Integrations
- FR-I1 REST API + API keys for The Bridge (read-only stats), OpenLeads (lead push), OmniCX (escalation ticket on complaint/threat/legal mention).
- FR-I2 Webhooks out: `appointment.created`, `appointment.updated`, `call.completed`.
- FR-I3 Optional ViciDial disposition sync via the existing `ops.altriacallcenter.com` API.

## 3. Non-functional
- NFR-1 Latency: end-of-prospect-speech → Maria starts speaking ≤ 1.0 s p50, ≤ 1.8 s p95.
- NFR-2 Reliability: a crashed worker must not leave leads stuck in `calling`; watchdog resets after 15 min.
- NFR-3 Concurrency: 10 simultaneous calls on one Railway worker (scale horizontally by adding workers; LiveKit dispatch load-balances).
- NFR-4 Security: secrets only in Railway variables; recordings in private bucket with signed URLs (15 min); RBAC on API; audit log on DNC/appointment changes.
- NFR-5 Data retention: recordings 180 days default (per campaign override); transcripts kept.
- NFR-6 Observability: per-call cost breakdown (STT/TTS/LLM/telephony seconds), error dashboards, Railway logs structured JSON.
- NFR-7 Multi-tenant ready: `client_id` on campaigns so a client can later get a read-only portal.
- NFR-8 Everything configurable per campaign; no campaign-specific code paths.

## 4. Compliance requirements (implemented as campaign flags + global checks)
- `ai_disclosure`: `on_ask` | `upfront` (default `on_ask` for B2B US, `upfront` where required).
- `recording_notice`: text spoken at start if `true`.
- Calling window enforced in prospect local time; default Mon–Fri 09:00–17:30 for B2B, never before 08:00 or after 21:00.
- Global DNC table + per-client DNC; immediate opt-out on "stop calling / remove me".
- Caller ID must be a number you own; inbound callbacks to that number should reach a human or an IVR that logs a callback request (Phase 4+).
- Retention and deletion endpoint for prospect data requests.

## 5. Out of scope (v1)
- Inbound call handling (except callback capture on the caller-ID number).
- Payment collection, contracts.
- Voice cloning of real human agents.
- Fully autonomous playbook changes without human approval.

## 6. Success metrics
- Pilot (YP SEO): ≥ 60 % of human-answered calls reach a real conversation (> 30 s), appointment rate vs. your human team's baseline, show rate ≥ 50 %, < 2 % complaint rate, cost per appointment below human cost.
