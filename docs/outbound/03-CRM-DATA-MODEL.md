# 03 — CRM Data Model, API and UI

Postgres 15+, extension `pgvector`. All tables have `id uuid pk default gen_random_uuid()`, `created_at`, `updated_at`. Use Alembic migrations. Timestamps are `timestamptz`; prospect-local times are derived from `leads.timezone`.

## 1. Schema

```sql
-- Tenancy / people
clients        (id, name, contact_email, notes, is_active)
users          (id, email unique, password_hash, full_name, role enum('admin','manager','rep','qa'),
                client_id null, is_active)
api_keys       (id, name, key_hash, scopes text[], client_id null, last_used_at)

-- Telephony config
sip_trunks     (id, name, market enum('US','CA','PH','OTHER'), livekit_trunk_id, provider,
                caller_ids text[], is_active)

-- Campaigns
campaigns      (id, client_id, name, status enum('draft','testing','active','paused','completed'),
                market, country_codes text[], default_timezone, languages text[],
                sip_trunk_id, caller_id,
                calling_window jsonb,          -- {"mon":[["09:00","17:30"]], ... } prospect-local
                max_attempts int default 3, retry_spacing_hours int default 4,
                voicemail_counts_as_attempt bool default false,
                concurrency int default 2, daily_cap int, daily_budget_usd numeric,
                test_mode bool default true, test_allowlist text[],
                appointment_settings jsonb,    -- type, duration_min, team_id, slots, buffer, lead_time_hours
                compliance jsonb,              -- ai_disclosure, recording_notice, dnc_scrub
                active_playbook_version_id, created_by)
playbook_versions (id, campaign_id, version int, playbook jsonb, json_schema_version text,
                notes, source enum('manual','learning','import'), created_by, is_active)
teams          (id, client_id, name, notify_emails text[], webhook_url, timezone)
team_members   (team_id, user_id)
availability_rules (id, team_id, weekday int, start_time, end_time, max_parallel int default 1)
availability_overrides (id, team_id, date, is_closed bool, start_time, end_time)

-- Leads
leads          (id, campaign_id, external_id, source enum('csv','openleads','manual','vicidial','api'),
                business_name, contact_name, contact_title, phone_e164, phone_alt_e164, email,
                address_line, city, region, postal_code, country_code, timezone,
                website, industry, custom jsonb,
                status enum('new','queued','calling','contacted','callback','appointment_set',
                            'not_interested','wrong_number','dnc','exhausted','invalid','paused'),
                attempts int default 0, next_attempt_at timestamptz, last_attempt_at,
                last_disposition text, priority int default 0, notes,
                unique(campaign_id, phone_e164))
lead_imports   (id, campaign_id, filename, row_count, imported, skipped_dupe, skipped_dnc,
                errors jsonb, column_map jsonb, created_by)

-- Calls
call_attempts  (id, lead_id, campaign_id, playbook_version_id, attempt_no,
                status enum('dialing','ringing','in_call','completed','failed','failed_stale'),
                sip_status text, sip_error text,
                amd_result enum('human','machine_vm','machine_ivr','machine_unavailable','uncertain') null,
                outcome enum('conversation','voicemail','ivr','no_answer','busy','failed',
                             'invalid_number','no_human','hung_up_early'),
                disposition text,             -- from playbook.dispositions keys
                started_at, answered_at, human_detected_at, ended_at, duration_sec, talk_sec,
                livekit_room, recording_url, recording_expires_at,
                transcript jsonb,              -- [{role, text, ts, latency_ms}]
                result jsonb,                  -- structured post-call JSON (04 §6)
                summary text, sentiment text, needs_review bool default false, review_reason text,
                stage_reached text, end_reason text,
                metrics jsonb, cost_usd numeric,
                appointment_id null)
call_events    (id, call_attempt_id, ts, type text, payload jsonb)   -- tool calls, stage changes, errors
call_reviews   (id, call_attempt_id, reviewer_id, score int, tags text[], comments, corrections jsonb)

-- Appointments
appointments   (id, lead_id, campaign_id, call_attempt_id, team_id, assigned_user_id null,
                type enum('phone','video','onsite'),
                start_at timestamptz, end_at timestamptz, prospect_timezone,
                location_address, meeting_link,
                status enum('scheduled','confirmed','rescheduled','cancelled','completed','no_show'),
                outcome enum('sold','follow_up','lost','pending') default 'pending', value numeric,
                notes, confirmation_sent_at, reminder_24h_sent_at, reminder_2h_sent_at)
appointment_events (id, appointment_id, ts, type, payload jsonb, actor_user_id null)

-- Compliance
dnc_entries    (id, phone_e164, scope enum('global','client'), client_id null, reason, source,
                created_by null, unique(phone_e164, scope, client_id))
consent_events (id, lead_id, call_attempt_id, type enum('opt_out','recording_ack','ai_disclosed'), ts)
audit_log      (id, actor_user_id, action, entity, entity_id, before jsonb, after jsonb, ts)

-- Learning
training_recordings (id, campaign_id, filename, storage_url, duration_sec, outcome_label text null,
                agent_name text null, uploaded_by, transcript jsonb, status enum('uploaded','transcribed','analyzed','failed'))
analysis_runs  (id, campaign_id, recording_ids uuid[], model, report jsonb, playbook_draft jsonb,
                eval_scenarios jsonb, status, created_by)
objection_library (id, campaign_id, objection text, rebuttal text, source enum('recording','qa','manual'),
                embedding vector(1024), effectiveness_score numeric null)
eval_scenarios (id, campaign_id, persona jsonb, expected_outcome text, script_hints text)
eval_runs      (id, campaign_id, playbook_version_id, scenario_id, transcript jsonb, passed bool, grader_notes)
```

Indexes: `leads(campaign_id,status,next_attempt_at)`, `call_attempts(campaign_id,started_at)`, `appointments(team_id,start_at)`, `dnc_entries(phone_e164)`, ivfflat on `objection_library.embedding`.

## 2. Lead status transitions (enforced in `dialer/state_machine.py`)

| From | Event | To |
|---|---|---|
| new / queued | scheduler picks | calling |
| calling | outcome no_answer/busy/voicemail/ivr and attempts < max | queued (next_attempt_at set) |
| calling | same, attempts ≥ max | exhausted |
| calling | conversation, disposition appointment_set | appointment_set |
| calling | disposition callback | callback (next_attempt_at from tool) |
| calling | not_interested | not_interested |
| calling | wrong_number | wrong_number |
| calling | dnc | dnc (+ dnc_entries insert) |
| calling | invalid_number | invalid |
| any | manual requeue | queued |
| appointment_set | appointment no_show + campaign.requeue_no_show | callback |

## 3. REST API (prefix `/api/v1`, JWT unless noted)

```
POST   /auth/login                          → {token}
GET    /me

GET/POST      /campaigns                    GET/PATCH/DELETE /campaigns/{id}
POST   /campaigns/{id}/actions/{start|pause|resume|complete|clone}
GET/POST      /campaigns/{id}/playbooks     POST /campaigns/{id}/playbooks/{vid}/activate
POST   /campaigns/{id}/playbooks/validate   → schema errors
POST   /campaigns/{id}/simulate             → text-chat turn with Maria (for UI simulator)
GET    /campaigns/{id}/stats?from&to        → funnel + cost + live_calls

POST   /campaigns/{id}/leads/import         (multipart csv + column_map json) → lead_import
POST   /campaigns/{id}/leads/import/openleads  {offer, filters}
GET    /campaigns/{id}/leads?status&q&page  POST /campaigns/{id}/leads
GET/PATCH /leads/{id}                        POST /leads/bulk {ids, action}
GET    /leads/{id}/timeline                 → attempts, appointments, events

GET    /calls?campaign_id&outcome&needs_review&from&to&page
GET    /calls/{id}                          → attempt + transcript + result + signed recording_url
POST   /calls/{id}/review                   {score, tags, comments, corrections}
POST   /calls/{id}/requeue-lead

GET    /appointments?team_id&from&to&status  GET/PATCH /appointments/{id}
POST   /appointments/{id}/actions/{confirm|cancel|reschedule|complete|no_show}
GET    /appointments/{id}/ics
GET    /teams/{id}/slots?from&to&duration    → available slots

GET/POST /dnc     DELETE /dnc/{id}     POST /dnc/check {phones[]}
GET/POST /teams   GET/POST /teams/{id}/availability
GET/POST /users   GET/POST /sip-trunks

POST   /learning/recordings (multipart)     GET /learning/recordings?campaign_id
POST   /learning/analyze {campaign_id, recording_ids[]} → analysis_run (async)
GET    /learning/analysis/{id}              POST /learning/analysis/{id}/create-playbook-draft
POST   /learning/evals/run {campaign_id, playbook_version_id} → eval_run ids
GET    /learning/objections?campaign_id

-- Internal (X-Internal-Secret), used by voice-worker
GET    /internal/dispatch-context/{attempt_id}     → lead, campaign, playbook, slots summary, trunk, caller_id
PATCH  /internal/calls/{attempt_id}                → status/sip/amd/timestamps/recording/result
POST   /internal/calls/{attempt_id}/events         → turn or event
POST   /internal/calls/{attempt_id}/tool/{name}    → executes tool, returns result JSON
-- Public/API key
GET    /public/stats?campaign_id     (The Bridge)
POST   /public/leads                 (OpenLeads push)
POST   /webhooks/livekit             (egress finished)
POST   /webhooks/telnyx              (inbound SMS replies: STOP → dnc)
```

## 4. Tool endpoint contracts (`/internal/calls/{id}/tool/{name}`)

| Tool | Input | Effect / return |
|---|---|---|
| `check_slots` | `{preferred_day?, preferred_part_of_day?, count?}` | returns ≤ 4 slots in prospect-local wording + ISO |
| `book_appointment` | `{slot_start_iso, type, contact_name, email?, address?, notes}` | creates appointment (status scheduled), lead→appointment_set, triggers confirmation; returns human-readable confirmation |
| `schedule_callback` | `{when_iso or relative_text, reason}` | lead→callback, next_attempt_at |
| `mark_not_interested` | `{reason}` | disposition |
| `mark_wrong_number` | `{note}` | disposition |
| `add_to_dnc` | `{reason}` | dnc_entries + consent_events opt_out |
| `send_info` | `{channel:'sms'|'email', template_key}` | queues message; returns ok |
| `transfer_to_human` | `{reason}` | returns SIP transfer target if allowed, else `{allowed:false}` |
| `escalate_complaint` | `{summary}` | OmniCX ticket (if configured), needs_review=true |
| `set_stage` | `{stage}` | call_events; stage_reached |
| `end_call` | `{disposition, farewell_said:bool}` | worker hangs up after farewell |

All tools are idempotent per attempt (booking twice returns the existing appointment).

## 5. UI screens (`apps/web/src/crm/`)

1. **Dashboard** — campaign selector, KPI tiles (dials, connects, human answered, conversations, appointments, appt rate, avg talk time, est. cost, live calls), funnel chart, hourly connect heatmap, recent calls.
2. **Campaigns** — list + create/edit form (tabs: General, Telephony, Schedule & Pacing, Appointments, Compliance, Playbook). Start/Pause buttons with test-mode banner.
3. **Leads** — import wizard (upload → map columns → preview dupes/DNC → confirm), table with filters, bulk actions, lead drawer with timeline.
4. **Calls** — table; detail page: player + transcript with clickable timestamps, structured result panel, tool-call timeline, QA form.
5. **Appointments** — week calendar + list; rep filter; detail drawer with actions; ICS download.
6. **Review queue** — needs_review calls and low-confidence dispositions; approve / correct disposition / requeue.
7. **Playbooks** — versions list, JSON editor (Monaco) with live schema validation, diff between versions, **Simulate** chat panel, activate.
8. **Learning** — upload recordings, run analysis, view report, create playbook draft, run evals, objection library.
9. **Settings** — users, teams & availability, SIP trunks, DNC list, API keys, webhooks.

Design: app shell with sidebar and Tailwind theme; tables via TanStack Table; audio via `<audio>` + wavesurfer optional.
