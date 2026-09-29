"""Idempotent dev/demo seed: `uv run python -m app.seed` (from apps/api) or scripts/seed.ps1.

Creates: admin user (SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD), client "YP", a placeholder SIP
trunk, campaign "YP SEO US (test)" in test_mode, and the two DNC numbers used by
scripts/sample_leads.csv. Never prints secrets; never overwrites an existing admin's password.
"""

import asyncio
import logging

from sqlalchemy import func, select

from app.config import get_settings
from app.crm.enums import CampaignStatus, DncScope, Market, UserRole
from app.crm.models import Campaign, Client, DncEntry, SipTrunk, User
from app.crm.schemas import AppointmentSettings, ComplianceSettings, default_calling_window
from app.crm.security import hash_password
from app.db import SessionLocal, engine
from app.logging import configure_logging

log = logging.getLogger("maria.seed")

CAMPAIGN_NAME = "YP SEO US (test)"
TRUNK_NAME = "Telnyx US (placeholder)"
# Phones in scripts/sample_leads.csv that must be skipped as DNC on import.
SAMPLE_DNC = ("+13125550149", "+639175550150")
AI_DISCLOSURE = (
    "Yes — I'm Maria, an AI assistant calling for the SEO team at Altria. Happy to keep it "
    "short, or I can have a person call you instead."
)


async def seed() -> dict[str, str]:
    settings = get_settings()
    pw = settings.seed_admin_password
    if pw is None or len(pw.get_secret_value()) < 8:
        raise SystemExit("Set SEED_ADMIN_PASSWORD (8+ chars) in .env before seeding.")
    email = settings.seed_admin_email.strip().lower()
    done: dict[str, str] = {}
    async with SessionLocal() as session:
        admin = await session.scalar(select(User).where(func.lower(User.email) == email))
        if admin is None:
            admin = User(
                email=email,
                password_hash=hash_password(settings.seed_admin_password.get_secret_value()),
                full_name="Admin",
                role=UserRole.admin,
            )
            session.add(admin)
            done["admin"] = f"created {email}"
        else:
            done["admin"] = f"exists {email} (password unchanged)"

        client = await session.scalar(select(Client).where(Client.name == "YP"))
        if client is None:
            client = Client(name="YP", notes="Yellow Pages SEO campaigns")
            session.add(client)
            done["client"] = "created YP"
        await session.flush()

        trunk = await session.scalar(select(SipTrunk).where(SipTrunk.name == TRUNK_NAME))
        if trunk is None:
            trunk = SipTrunk(
                name=TRUNK_NAME,
                market=Market.US,
                provider="telnyx",
                livekit_trunk_id=None,  # fill in after `lk sip outbound create` (Phase 2)
                caller_ids=[],
                is_active=False,
            )
            session.add(trunk)
            done["sip_trunk"] = f"created {TRUNK_NAME}"
        await session.flush()

        campaign = await session.scalar(select(Campaign).where(Campaign.name == CAMPAIGN_NAME))
        if campaign is None:
            session.add(
                Campaign(
                    client_id=client.id,
                    name=CAMPAIGN_NAME,
                    status=CampaignStatus.draft,
                    market=Market.US,
                    country_codes=["US", "CA"],
                    default_timezone="America/New_York",
                    languages=["en"],
                    sip_trunk_id=trunk.id,
                    calling_window=default_calling_window(),
                    test_mode=True,
                    test_allowlist=[],
                    appointment_settings=AppointmentSettings().model_dump(mode="json"),
                    compliance=ComplianceSettings(ai_disclosure_text=AI_DISCLOSURE).model_dump(
                        mode="json"
                    ),
                    created_by=admin.id,
                )
            )
            done["campaign"] = f"created {CAMPAIGN_NAME} (test_mode)"

        for phone in SAMPLE_DNC:
            exists = await session.scalar(
                select(DncEntry.id).where(
                    DncEntry.phone_e164 == phone, DncEntry.scope == DncScope.global_
                )
            )
            if not exists:
                session.add(
                    DncEntry(
                        phone_e164=phone,
                        scope=DncScope.global_,
                        reason="sample data: opted out",
                        source="seed",
                    )
                )
                done[f"dnc {phone}"] = "created"
        await session.commit()
    await engine.dispose()
    return done


def main() -> None:
    configure_logging(get_settings().log_level)
    for key, value in asyncio.run(seed()).items():
        log.info("seed", extra={"item": key, "result": value})


if __name__ == "__main__":
    main()
