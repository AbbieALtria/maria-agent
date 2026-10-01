"""Place a test call and follow it live.

    uv run python scripts/test_call.py [--lead <lead_id>] [--api http://localhost:8000]
    (or scripts/test_call.ps1)

Logs in as the seed admin (SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD from .env, or prompts), finds the
test lead (phone TEST_PHONE in campaign "YP SEO US (test)") unless --lead is given, calls
POST /campaigns/{id}/test-call, then polls GET /calls/{attempt_id} and prints status changes,
transcript lines and tool calls as they arrive, and finally the result JSON.
"""

import argparse
import getpass
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_NAME = "YP SEO US (test)"
POLL_SEC = 1.0
TIMEOUT_SEC = 15 * 60
FINAL = {"completed", "failed", "failed_stale"}


def fail(msg: str, r: httpx.Response | None = None) -> None:
    detail = ""
    if r is not None:
        try:
            detail = f" ({r.status_code}: {r.json().get('detail', r.text)})"
        except ValueError:
            detail = f" ({r.status_code})"
    sys.exit(f"error: {msg}{detail}")


def login(http: httpx.Client) -> None:
    email = os.environ.get("SEED_ADMIN_EMAIL", "admin@altria.local")
    password = os.environ.get("SEED_ADMIN_PASSWORD") or getpass.getpass(f"Password for {email}: ")
    r = http.post("/api/v1/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        fail("login failed", r)
    http.headers["Authorization"] = f"Bearer {r.json()['token']}"


def find_target(http: httpx.Client, lead_id: str | None) -> tuple[str, str]:
    r = http.get("/api/v1/campaigns")
    if r.status_code != 200:
        fail("could not list campaigns", r)
    campaign = next((c for c in r.json() if c["name"] == CAMPAIGN_NAME), None)
    if campaign is None:
        fail(f"campaign '{CAMPAIGN_NAME}' not found; run scripts/seed.ps1 and scripts/lk_setup.ps1")
    if lead_id:
        return campaign["id"], lead_id
    phone = os.environ.get("TEST_PHONE", "")
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        fail("TEST_PHONE is not set in .env (or pass --lead)")
    r = http.get(f"/api/v1/campaigns/{campaign['id']}/leads", params={"q": digits})
    items = r.json().get("items", []) if r.status_code == 200 else []
    if not items:
        fail("test lead not found; run scripts/lk_setup.ps1")
    return campaign["id"], items[0]["id"]


def follow(http: httpx.Client, attempt_id: str) -> dict:
    seen_turns = seen_events = 0
    last_status = None
    started = time.monotonic()
    while time.monotonic() - started < TIMEOUT_SEC:
        r = http.get(f"/api/v1/calls/{attempt_id}")
        if r.status_code != 200:
            fail("could not read the call", r)
        call = r.json()
        status = (call["status"], call.get("amd_result"))
        if status != last_status:
            amd = f" (AMD: {call['amd_result']})" if call.get("amd_result") else ""
            print(f"[status] {call['status']}{amd}")
            last_status = status
        for turn in call["transcript"][seen_turns:]:
            who = "Maria   " if turn["role"] == "assistant" else "Prospect"
            lat = f"  ({turn['latency_ms']} ms)" if turn.get("latency_ms") is not None else ""
            print(f"  {who}: {turn['text']}{lat}")
        seen_turns = len(call["transcript"])
        for ev in call["events"][seen_events:]:
            p = ev["payload"]
            if ev["type"] == "tool":
                print(f"  [tool] {p.get('name')} {json.dumps(p.get('args'))} -> "
                      f"{json.dumps(p.get('result'))}")  # fmt: skip
            else:
                print(f"  [{ev['type']}] {json.dumps(p)}")
        seen_events = len(call["events"])
        if call["status"] in FINAL and call.get("outcome"):
            return call
        time.sleep(POLL_SEC)
    fail("timed out waiting for the call to finish")
    raise AssertionError


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lead", help="lead id (default: the TEST_PHONE lead)")
    parser.add_argument("--api", default=os.environ.get("API_BASE_URL", "http://localhost:8000"))
    args = parser.parse_args()

    with httpx.Client(base_url=args.api.rstrip("/"), timeout=30) as http:
        try:
            http.get("/health").raise_for_status()
        except httpx.HTTPError:
            fail(f"API not reachable at {args.api}; start it with scripts/dev.ps1")
        login(http)
        campaign_id, lead_id = find_target(http, args.lead)
        r = http.post(f"/api/v1/campaigns/{campaign_id}/test-call", json={"lead_id": lead_id})
        if r.status_code != 200:
            fail("test call refused", r)
        attempt_id = r.json()["attempt_id"]
        print(f"Dispatched attempt {attempt_id} (room {r.json()['room']}). Your phone should ring.")
        call = follow(http, attempt_id)

    print("\n=== Result ===")
    print(f"outcome: {call['outcome']}   disposition: {call['disposition']}   "
          f"end_reason: {call['end_reason']}")  # fmt: skip
    if call.get("sip_status") or call.get("sip_error"):
        print(f"sip: {call.get('sip_status')} {call.get('sip_error')}")
    print(f"lead status: {call['lead']['status']}   attempts: {call['lead']['attempts']}")
    if call.get("appointment"):
        a = call["appointment"]
        tz = a["prospect_timezone"] or "UTC"
        start = datetime.fromisoformat(a["start_at"]).astimezone(ZoneInfo(tz))
        print(f"appointment: {start:%a %b %d %I:%M %p} {tz}, {a['type']}, {a['status']}")
    metrics = call.get("metrics") or {}
    if metrics:
        print(f"latency p50/p95: {metrics.get('latency_p50_ms')} / "
              f"{metrics.get('latency_p95_ms')} ms over {metrics.get('turns')} turns")  # fmt: skip
    print("result JSON:")
    print(json.dumps(call.get("result"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
