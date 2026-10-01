"""Phase 2 test-call setup (docs/outbound/02-ARCHITECTURE.md §7). Idempotent; safe to re-run.

    uv run python scripts/lk_setup.py          (or scripts/lk_setup.ps1)

1. Appends a generated INTERNAL_API_SECRET to .env if it has none (never printed).
2. LiveKit: creates the SIP outbound trunk "telnyx-us" (sip.telnyx.com, numbers [TELNYX_NUMBER],
   Telnyx SIP credentials), or updates it to match .env if it already exists.
3. DB: upserts the sip_trunks row, points campaign "YP SEO US (test)" at it (caller_id,
   test_mode on, test_allowlist [TEST_PHONE]), saves packages/playbook-schema/examples/
   yp_seo_us.json as the active playbook version, and upserts the lead "Test Business" / "Abbie"
   with phone TEST_PHONE.

Needs in .env: DATABASE_URL, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET,
TELNYX_SIP_USERNAME, TELNYX_SIP_PASSWORD, TELNYX_NUMBER, TEST_PHONE. Run scripts/seed.ps1 first.
"""

import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"
EXAMPLE_PLAYBOOK = REPO_ROOT / "packages" / "playbook-schema" / "examples" / "yp_seo_us.json"
TRUNK_NAME = "telnyx-us"
CAMPAIGN_NAME = "YP SEO US (test)"
TELNYX_ADDRESS = "sip.telnyx.com"
REQUIRED = (
    "DATABASE_URL",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "TELNYX_SIP_USERNAME",
    "TELNYX_SIP_PASSWORD",
    "TELNYX_NUMBER",
    "TEST_PHONE",
)


def ensure_internal_secret(env_path: Path) -> bool:
    """Append INTERNAL_API_SECRET=<random> to .env when missing or empty. Returns True if added."""
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "INTERNAL_API_SECRET" and value.strip():
            return False
    key = "INTERNAL_API_SECRET"
    lines = [ln for ln in text.splitlines() if ln.partition("=")[0].strip() != key]
    lines.append(f"INTERNAL_API_SECRET={secrets.token_urlsafe(48)}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH, override=False)


async def ensure_livekit_trunk(caller_id: str) -> str:
    """Create or update the LiveKit outbound trunk; returns its id."""
    from livekit import api

    lk = api.LiveKitAPI(
        os.environ["LIVEKIT_URL"], os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]
    )
    username = os.environ["TELNYX_SIP_USERNAME"]
    password = os.environ["TELNYX_SIP_PASSWORD"]
    try:
        existing = await lk.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest())
        match = [t for t in existing.items if t.name == TRUNK_NAME]
        if match:
            trunk = match[0]
            await lk.sip.update_outbound_trunk_fields(
                trunk.sip_trunk_id,
                address=TELNYX_ADDRESS,
                numbers=[caller_id],
                auth_username=username,
                auth_password=password,
            )
            print(f"LiveKit trunk '{TRUNK_NAME}' exists ({trunk.sip_trunk_id}); synced with .env")
            return trunk.sip_trunk_id
        trunk = await lk.sip.create_outbound_trunk(
            api.CreateSIPOutboundTrunkRequest(
                trunk=api.SIPOutboundTrunkInfo(
                    name=TRUNK_NAME,
                    address=TELNYX_ADDRESS,
                    numbers=[caller_id],
                    auth_username=username,
                    auth_password=password,
                )
            )
        )
        print(f"LiveKit trunk '{TRUNK_NAME}' created ({trunk.sip_trunk_id})")
        return trunk.sip_trunk_id
    finally:
        await lk.aclose()


async def configure_test_campaign(
    session: Any,
    *,
    livekit_trunk_id: str,
    caller_id: str,
    test_phone: str,
    playbook: dict[str, Any],
) -> dict[str, str]:
    """DB part (also used by the API tests). Commits; returns ids for the summary."""
    from sqlalchemy import func, select

    from app.config import get_settings
    from app.crm.audit import audit, snapshot
    from app.crm.enums import LeadSource, LeadStatus, Market, PlaybookSource
    from app.crm.models import Campaign, DncEntry, Lead, PlaybookVersion, SipTrunk, User
    from maria_shared.timezone import infer_timezone
    from playbook_schema import Playbook

    Playbook.model_validate(playbook)  # refuse to activate an invalid playbook
    actor = await session.scalar(
        select(User).where(func.lower(User.email) == get_settings().seed_admin_email.lower())
    )

    trunk = await session.scalar(select(SipTrunk).where(SipTrunk.name == TRUNK_NAME))
    before = snapshot(trunk) if trunk else None
    if trunk is None:
        trunk = SipTrunk(name=TRUNK_NAME, market=Market.US)
        session.add(trunk)
    trunk.provider = "telnyx"
    trunk.livekit_trunk_id = livekit_trunk_id
    trunk.caller_ids = [caller_id]
    trunk.is_active = True
    await session.flush()
    await session.refresh(trunk)  # load server-side timestamps before snapshotting
    audit(session, actor, "sip_trunk.upsert", "sip_trunk", trunk.id, before, snapshot(trunk))

    campaign = await session.scalar(select(Campaign).where(Campaign.name == CAMPAIGN_NAME))
    if campaign is None:
        raise SystemExit(f"Campaign '{CAMPAIGN_NAME}' not found: run scripts/seed.ps1 first.")
    before = snapshot(campaign)
    campaign.sip_trunk_id = trunk.id
    campaign.caller_id = caller_id
    campaign.test_mode = True
    campaign.test_allowlist = [test_phone]

    current = (
        await session.get(PlaybookVersion, campaign.active_playbook_version_id)
        if campaign.active_playbook_version_id
        else None
    )
    if current is None or current.playbook != playbook:
        latest = await session.scalar(
            select(func.max(PlaybookVersion.version)).where(
                PlaybookVersion.campaign_id == campaign.id
            )
        )
        pv = PlaybookVersion(
            campaign_id=campaign.id,
            version=(latest or 0) + 1,
            playbook=playbook,
            json_schema_version=playbook.get("schema_version"),
            notes="examples/yp_seo_us.json via scripts/lk_setup.py",
            source=PlaybookSource.import_,
            created_by=actor.id if actor else None,
        )
        session.add(pv)
        await session.flush()
        others = await session.scalars(
            select(PlaybookVersion).where(
                PlaybookVersion.campaign_id == campaign.id, PlaybookVersion.is_active.is_(True)
            )
        )
        for other in others:
            other.is_active = False
        pv.is_active = True
        campaign.active_playbook_version_id = pv.id
        # Activation is a human action: whoever runs this script, recorded as the seed admin.
        audit(
            session, actor, "playbook.activate", "playbook_version", pv.id,
            {"previous_version_id": str(current.id) if current else None},
            {"version": pv.version, "test_mode": True, "via": "scripts/lk_setup.py"},
        )  # fmt: skip
        current = pv
    await session.flush()
    await session.refresh(campaign)
    audit(session, actor, "campaign.update", "campaign", campaign.id, before, snapshot(campaign))

    lead = await session.scalar(
        select(Lead).where(Lead.campaign_id == campaign.id, Lead.phone_e164 == test_phone)
    )
    if lead is None:
        lead = Lead(campaign_id=campaign.id, phone_e164=test_phone, source=LeadSource.manual)
        session.add(lead)
    lead.business_name = "Test Business"
    lead.contact_name = "Abbie"
    lead.timezone = lead.timezone or infer_timezone(test_phone, fallback=campaign.default_timezone)
    if lead.status == LeadStatus.calling:
        print("note: the test lead is marked 'calling' (an earlier call did not finish).")
    await session.flush()
    on_dnc = await session.scalar(select(DncEntry.id).where(DncEntry.phone_e164 == test_phone))
    await session.commit()
    return {
        "sip_trunk_id": str(trunk.id),
        "livekit_trunk_id": livekit_trunk_id,
        "campaign_id": str(campaign.id),
        "playbook_version": str(current.version),
        "lead_id": str(lead.id),
        "lead_timezone": lead.timezone or "",
        "test_phone_on_dnc": "YES - remove it in Settings > DNC" if on_dnc else "no",
    }


async def main() -> None:
    if ensure_internal_secret(ENV_PATH):
        print("INTERNAL_API_SECRET generated and appended to .env (restart the API if running)")
    load_env()
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")

    from maria_shared.phone import normalize_phone

    caller_id = normalize_phone(os.environ["TELNYX_NUMBER"], "US")
    test_phone = normalize_phone(os.environ["TEST_PHONE"], "US")
    playbook = json.loads(EXAMPLE_PLAYBOOK.read_text(encoding="utf-8"))

    livekit_trunk_id = await ensure_livekit_trunk(caller_id)

    from app.db import SessionLocal, engine

    async with SessionLocal() as session:
        summary = await configure_test_campaign(
            session,
            livekit_trunk_id=livekit_trunk_id,
            caller_id=caller_id,
            test_phone=test_phone,
            playbook=playbook,
        )
    await engine.dispose()
    print("Test-call setup done:")
    for key, value in summary.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
