# 05 — Learning from Human-Agent Recordings

Goal: you upload recordings of your best human agents (e.g., the YP SEO team), and the system turns them into (1) a campaign playbook draft, (2) an objection/rebuttal library, (3) an FAQ/facts list, (4) style notes, and (5) simulated-prospect test scenarios that Maria must pass before going live. **This is prompt/playbook learning, not model fine-tuning and not voice cloning.** It is faster, cheaper, reviewable, and reversible.

## 1. Inputs
- Audio files (mp3/wav/m4a, mono or stereo). Stereo with agent/prospect on separate channels is ideal (ViciDial can record that way — enable if possible).
- Optional per-file metadata: agent name, outcome (`appointment` / `no_appointment`), campaign, date.
- Optional existing scripts, rebuttal sheets, product one-pagers (PDF/DOCX/TXT) → ingested as `facts` candidates.
- Consent: agents informed their calls are used for training; prospect PII is redacted in stored transcripts (`redact=true` in Deepgram, plus a regex pass for emails/phones).

## 2. Pipeline (api `learning/` module, background jobs)

```
upload → storage → transcribe (Deepgram batch: nova-3, diarize=true, smart_format, utterances,
   redact=pci,ssn; multichannel=true when stereo)
→ speaker labeling (which speaker is the agent: heuristic = speaks first with company name;
   fallback: Claude labels)
→ per-call analysis (Claude, analysis model)  →  call_analysis JSON
→ corpus synthesis across all calls (Claude, larger context)  →  analysis_runs.report
→ playbook draft (Claude renders report into playbook JSON, validated against schema)
→ eval scenarios (Claude generates 15–30 prospect personas from real calls)
→ human review in UI → activate as playbook version (source='learning')
```

### 2.1 Per-call analysis JSON
```jsonc
{
  "outcome": "appointment|callback|not_interested|...",
  "opener_text": "...", "permission_ask": "...", "reason_for_call": "...",
  "qualifying_questions": ["..."],
  "pitch_points": ["..."],
  "objections": [{ "prospect_said": "...", "agent_response": "...", "worked": true }],
  "close_attempts": ["..."], "confirmation_text": "...",
  "facts_stated": ["..."], "promises_or_claims": ["..."],     // flag risky claims
  "tone_notes": "...", "pace_wpm": 150, "agent_talk_ratio": 0.55,
  "moments_that_went_well": ["..."], "moments_that_went_badly": ["..."],
  "prospect_persona": { "role": "owner", "mood": "busy", "objection_style": "price-first" }
}
```

### 2.2 Corpus synthesis report
- Winning opener variants (ranked by appointment rate).
- Best-performing rebuttal per objection cluster (cluster by embedding similarity on `prospect_said`).
- Qualifying questions that appear in successful calls.
- Facts/claims list with a **risk column** (things agents said that Maria must NOT say without confirmation).
- Style profile: average sentence length, filler words used, formality, humor, Taglish ratio (PH).
- Funnel where humans lose prospects (stage drop-off) → tells you where to focus Maria's flow.
- Draft `dispositions` mapping to your ViciDial codes (YPVM, YPCBCK, YPNI, YPNA, …) if the campaign uses them.

### 2.3 Playbook draft generation
Prompt the analysis model with the report + the JSON Schema + `04` example → output validated playbook. Store as `playbook_versions` (is_active=false) with `notes="Generated from N recordings, run <id>"`. UI shows a diff versus the active version.

### 2.4 Eval scenarios & simulation harness
- Each scenario: persona (role, mood, objections they will raise, whether they eventually agree), `expected_outcome`, `must_happen` (e.g., "Maria discloses AI when asked"), `must_not_happen` ("quote a price").
- `learning/evals/run`: for each scenario, Claude plays the prospect in **text** against Maria's live prompt/tools (no telephony), 12-turn cap; a grader model scores pass/fail against must/must-not rules and disposition correctness. Store transcripts in `eval_runs`.
- Gate: a playbook version can be activated on a non-test campaign only if the latest eval run passes ≥ 90 % and all compliance scenarios pass. (Admin override with audit log.)
- Later (Phase 6+): a voice-loop variant where a second LiveKit agent plays the prospect over audio, to catch STT/TTS issues.

## 3. Continuous improvement loop
1. QA grades Maria's real calls (`call_reviews`); corrections include "better response" text.
2. Nightly job clusters failed objections from `call_attempts.result.objections[handled=false]` + QA corrections into `objection_library` (embeddings, pgvector).
3. "Suggest playbook update" button → Claude proposes a diff (new rebuttals, tightened opener) → new draft version → evals → human activates.
4. Track appointment rate per playbook version in the dashboard; roll back with one click.

## 4. Taglish STT gate (Phase 7)
- Script `scripts/taglish_stt_eval.py`: takes 30 short PH clips with human reference transcripts; runs Deepgram `nova-3` with `language=tl`, `language=multi`, and `en` (as baseline), computes WER and a "key-info accuracy" score (names, numbers, addresses, dates). Also try one alternative provider (e.g., Google Chirp/Speech v2 `fil-PH`, or another vendor) via a pluggable interface.
- Pass if key-info accuracy ≥ 90 % and WER acceptable to you on listening review. If fail: PH campaigns run English-first with Maria asking permission to continue in English, until STT improves or an alternative is adopted.

## 5. What Claude Code must NOT do here
- No fine-tuning jobs, no voice cloning of agents.
- No storing raw PII of prospects from training recordings beyond the redacted transcript.
- No auto-activation of generated playbooks.
