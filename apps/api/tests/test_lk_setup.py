"""scripts/lk_setup.py: .env secret generation and the idempotent DB part."""

import importlib.util
from pathlib import Path

from sqlalchemy import func, select
from tests.conftest import EXAMPLE_PLAYBOOK

from app.crm.models import Campaign, Lead, PlaybookVersion, SipTrunk

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "lk_setup.py"
spec = importlib.util.spec_from_file_location("lk_setup", SCRIPT)
lk_setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lk_setup)

TEST_PHONE = "+12125550123"
CALLER_ID = "+12014621616"


def test_ensure_internal_secret(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=x\nINTERNAL_API_SECRET=\n", encoding="utf-8")
    assert lk_setup.ensure_internal_secret(env) is True
    lines = env.read_text(encoding="utf-8").splitlines()
    secrets_ = [ln for ln in lines if ln.startswith("INTERNAL_API_SECRET=")]
    assert len(secrets_) == 1 and len(secrets_[0]) > 50 and "DATABASE_URL=x" in lines
    assert lk_setup.ensure_internal_secret(env) is False  # kept as-is on re-run
    assert env.read_text(encoding="utf-8").splitlines() == lines


def test_ensure_internal_secret_creates_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    assert lk_setup.ensure_internal_secret(env) is True
    assert env.read_text(encoding="utf-8").startswith("INTERNAL_API_SECRET=")


async def test_configure_test_campaign_is_idempotent(db_session, campaign) -> None:
    kwargs = dict(
        livekit_trunk_id="ST_abc", caller_id=CALLER_ID, test_phone=TEST_PHONE,
        playbook=EXAMPLE_PLAYBOOK,
    )  # fmt: skip
    first = await lk_setup.configure_test_campaign(db_session, **kwargs)
    second = await lk_setup.configure_test_campaign(db_session, **kwargs)
    assert first == second and first["playbook_version"] == "1"

    await db_session.refresh(campaign)
    trunk = await db_session.get(SipTrunk, campaign.sip_trunk_id)
    assert trunk.name == "telnyx-us" and trunk.livekit_trunk_id == "ST_abc"
    assert trunk.caller_ids == [CALLER_ID]
    assert campaign.caller_id == CALLER_ID and campaign.test_mode is True
    assert campaign.test_allowlist == [TEST_PHONE]
    pv = await db_session.get(PlaybookVersion, campaign.active_playbook_version_id)
    assert pv.is_active and pv.playbook == EXAMPLE_PLAYBOOK
    lead = await db_session.scalar(select(Lead).where(Lead.campaign_id == campaign.id))
    assert (lead.business_name, lead.contact_name) == ("Test Business", "Abbie")
    assert lead.timezone == "America/New_York"
    n = await db_session.scalar(select(func.count()).select_from(Lead))
    assert n == 1

    # A changed playbook becomes a new active version.
    changed = {**EXAMPLE_PLAYBOOK, "never_say": ["changed"]}
    third = await lk_setup.configure_test_campaign(db_session, **{**kwargs, "playbook": changed})
    assert third["playbook_version"] == "2"
    active = await db_session.scalars(
        select(PlaybookVersion.version).where(PlaybookVersion.is_active.is_(True))
    )
    assert list(active) == [2]
    assert (await db_session.get(Campaign, campaign.id)).active_playbook_version_id is not None
