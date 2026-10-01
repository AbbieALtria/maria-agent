"""Snapshot of the assembled system prompt. Regenerate with UPDATE_SNAPSHOTS=1 after a deliberate
prompt change and review the diff."""

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playbook_schema import EXAMPLES_DIR, Playbook, build_system_prompt
from playbook_schema.prompt import opt_out_regex, placeholder_values, render

SNAPSHOT = Path(__file__).parent / "snapshots" / "yp_seo_us_prompt.txt"
LEAD = {
    "business_name": "Test Business",
    "contact_name": "Abbie Smith",
    "city": "Newark",
    "custom": {"rating": 4.5},
}
SLOTS = [
    {"label": "Friday, October 2 at 10:00 AM", "start_iso": "2026-10-02T10:00:00-04:00"},
    {"label": "Friday, October 2 at 2:00 PM", "start_iso": "2026-10-02T14:00:00-04:00"},
]


def _playbook() -> Playbook:
    return Playbook.model_validate(
        json.loads((EXAMPLES_DIR / "yp_seo_us.json").read_text(encoding="utf-8"))
    )


def test_prompt_snapshot() -> None:
    now = datetime(2026, 10, 1, 9, 5, tzinfo=ZoneInfo("America/New_York"))
    prompt = build_system_prompt(_playbook(), LEAD, now, SLOTS)
    if os.environ.get("UPDATE_SNAPSHOTS") or not SNAPSHOT.exists():
        SNAPSHOT.write_text(prompt, encoding="utf-8")
    assert prompt == SNAPSHOT.read_text(encoding="utf-8")


def test_section_order_and_no_leftover_placeholders() -> None:
    now = datetime(2026, 10, 1, 9, 5, tzinfo=ZoneInfo("America/New_York"))
    prompt = build_system_prompt(_playbook(), LEAD, now, SLOTS)
    positions = [prompt.index(f"# {n}.") for n in range(1, 11)]
    assert positions == sorted(positions)
    assert "{" not in prompt
    assert "Never claim or imply that you are human" in prompt
    assert "Hi Abbie" in prompt and "I've got Friday, October 2 at 10:00 AM or" in prompt


def test_placeholder_defaults_for_sparse_lead() -> None:
    values = placeholder_values(_playbook(), {}, [])
    assert values["first_name"] == "there"
    assert values["contact_name_or_the_owner"] == "the owner"
    assert values["industry"] == "unknown"
    assert render("Hi {first_name} at {mystery}", values) == "Hi there at {mystery}"


def test_opt_out_regex() -> None:
    rx = opt_out_regex(_playbook())
    assert rx.search("Please REMOVE MY NUMBER now")
    assert rx.search("just stop calling me")
    assert not rx.search("tell me more")
