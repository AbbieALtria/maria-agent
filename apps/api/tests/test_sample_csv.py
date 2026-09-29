"""The shipped scripts/sample_leads.csv imports as 45 new / 3 duplicate / 2 DNC (Phase 1
acceptance) with the seed's DNC numbers in place."""

from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import select

from app.crm.enums import DncScope
from app.crm.models import DncEntry, Lead
from app.seed import SAMPLE_DNC

SAMPLE = Path(__file__).resolve().parents[3] / "scripts" / "sample_leads.csv"


async def test_sample_csv(client: AsyncClient, admin_headers, campaign, db_session) -> None:
    db_session.add_all(DncEntry(phone_e164=p, scope=DncScope.global_) for p in SAMPLE_DNC)
    await db_session.flush()
    r = await client.post(
        f"/api/v1/campaigns/{campaign.id}/leads/import",
        files={"file": ("sample_leads.csv", SAMPLE.read_bytes(), "text/csv")},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["row_count"] == 50
    assert (report["imported"], report["skipped_dupe"], report["skipped_dnc"]) == (45, 3, 2)
    assert report["skipped_invalid"] == 0
    assert report["column_map"]["phone"] == "Phone"
    assert report["column_map"]["region"] == "State/Province"

    leads = list(await db_session.scalars(select(Lead).where(Lead.campaign_id == campaign.id)))
    by_country: dict[str, int] = {}
    for lead in leads:
        by_country[lead.country_code] = by_country.get(lead.country_code, 0) + 1
        assert lead.timezone, lead.phone_e164
        if lead.country_code == "PH":
            assert lead.timezone == "Asia/Manila"
    assert by_country == {"US": 25, "CA": 10, "PH": 10}
    tz = {lead.city: lead.timezone for lead in leads}
    assert tz["Honolulu"] == "Pacific/Honolulu"
    assert tz["Phoenix"] == "America/Phoenix"
    assert tz["Vancouver"] == "America/Vancouver"
    assert tz["St. John's"] == "America/St_Johns"
    assert tz["Regina"] == "America/Regina"
    assert all("Google Rating" in lead.custom for lead in leads)
