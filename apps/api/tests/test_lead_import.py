import json

from httpx import AsyncClient
from sqlalchemy import func, select

from app.crm.enums import DncScope, LeadStatus
from app.crm.models import Campaign, Client, DncEntry, Lead, LeadImport
from app.crm.services.lead_import import suggest_column_map

CSV = """Company,Contact,Phone Number,State/Province,Country,Rating
Acme Plumbing,Ann,(312) 555-0101,IL,US,4.5
Best Dental,Bob,212-555-0102,NY,USA,4.9
Acme Plumbing dup,Ann,+1 312 555 0101,IL,US,4.5
Maple Cafe,Cid,416-555-0103,ON,Canada,
Manila Clean,Dee,0917 555 0104,,Philippines,
Blocked Co,Eve,305-555-0105,FL,US,
Client Blocked,Fay,206-555-0106,WA,US,
Bad Phone,Gus,555-01,TX,US,
Empty Phone,Hal,,TX,US,
Unknown Region,Ivy,(303) 555-0107,,,
"""


async def _import(client: AsyncClient, campaign: Campaign, headers, csv_text=CSV, **form):
    data = {k: (json.dumps(v) if isinstance(v, dict) else str(v).lower()) for k, v in form.items()}
    return await client.post(
        f"/api/v1/campaigns/{campaign.id}/leads/import",
        files={"file": ("leads.csv", csv_text.encode(), "text/csv")},
        data=data,
        headers=headers,
    )


async def _seed_dnc(db_session, yp_client: Client) -> None:
    db_session.add_all(
        [
            DncEntry(phone_e164="+13055550105", scope=DncScope.global_, reason="test"),
            DncEntry(phone_e164="+12065550106", scope=DncScope.client, client_id=yp_client.id),
        ]
    )
    await db_session.flush()


def test_suggest_column_map() -> None:
    m = suggest_column_map(["Company", "Contact", "Phone Number", "State/Province", "Country", "X"])
    assert m == {
        "phone": "Phone Number",
        "business_name": "Company",
        "contact_name": "Contact",
        "region": "State/Province",
        "country_code": "Country",
    }


async def test_import_report_counts(
    client: AsyncClient, admin_headers, campaign: Campaign, yp_client, db_session
) -> None:
    await _seed_dnc(db_session, yp_client)
    resp = await _import(client, campaign, admin_headers)
    assert resp.status_code == 200, resp.text
    r = resp.json()
    assert r["row_count"] == 10
    assert r["imported"] == 5
    assert r["skipped_dupe"] == 1
    assert r["skipped_dnc"] == 2
    assert r["skipped_invalid"] == 2
    reasons = {(i["row"], i["reason"]) for i in r["issues"]}
    assert reasons == {(3, "duplicate"), (6, "dnc"), (7, "dnc"), (8, "invalid"), (9, "invalid")}

    leads = {
        lead.phone_e164: lead
        for lead in await db_session.scalars(select(Lead).where(Lead.campaign_id == campaign.id))
    }
    assert set(leads) == {
        "+13125550101", "+12125550102", "+14165550103", "+639175550104", "+13035550107",
    }  # fmt: skip
    assert leads["+13125550101"].timezone == "America/Chicago"
    assert leads["+13125550101"].custom == {"Rating": "4.5"}
    assert leads["+12125550102"].country_code == "US"
    assert leads["+14165550103"].timezone == "America/Toronto"
    assert leads["+14165550103"].country_code == "CA"
    assert leads["+639175550104"].timezone == "Asia/Manila"
    assert leads["+13035550107"].timezone == "America/Denver"  # from area code
    assert all(lead.status == LeadStatus.new for lead in leads.values())

    record = await db_session.get(LeadImport, r["import_id"])
    assert record is not None and record.imported == 5 and record.skipped_dnc == 2


async def test_reimport_all_dupes(client: AsyncClient, admin_headers, campaign) -> None:
    first = (await _import(client, campaign, admin_headers)).json()
    second = (await _import(client, campaign, admin_headers)).json()
    assert second["imported"] == 0
    assert second["skipped_dupe"] == first["imported"] + first["skipped_dupe"]


async def test_dry_run_writes_nothing(
    client: AsyncClient, admin_headers, campaign, db_session
) -> None:
    r = (await _import(client, campaign, admin_headers, dry_run=True)).json()
    assert r["dry_run"] is True and r["import_id"] is None
    assert r["imported"] == 7  # no DNC seeded: 10 rows − 1 dupe − 2 invalid
    count = await db_session.scalar(select(func.count()).select_from(Lead))
    assert count == 0
    assert r["headers"][0] == "Company"
    assert r["preview"][0]["status"] == "ok"


async def test_explicit_column_map_and_missing_phone(
    client: AsyncClient, admin_headers, campaign
) -> None:
    bad = await _import(client, campaign, admin_headers, column_map={"business_name": "Company"})
    assert bad.status_code == 422 and "phone" in bad.json()["detail"]
    unknown = await _import(
        client, campaign, admin_headers, column_map={"phone": "Phone Number", "shoe_size": "X"}
    )
    assert unknown.status_code == 422
    ok = await _import(
        client, campaign, admin_headers,
        column_map={"phone": "Phone Number", "business_name": "Contact"},
    )  # fmt: skip
    body = ok.json()
    assert ok.status_code == 200
    # Unmapped columns (incl. Company) land in custom.
    assert body["column_map"] == {"phone": "Phone Number", "business_name": "Contact"}


async def test_default_region_from_campaign(
    client: AsyncClient, admin_headers, campaign, db_session
) -> None:
    csv_text = "name,phone\nNo Country,(415) 555-0199\nPH no prefix,0917 555 0198\n"
    r = (await _import(client, campaign, admin_headers, csv_text=csv_text)).json()
    # campaign.country_codes = [US, CA] → the PH local number is not valid as a US number
    assert r["imported"] == 1 and r["skipped_invalid"] == 1
    lead = await db_session.scalar(select(Lead).where(Lead.campaign_id == campaign.id))
    assert lead.phone_e164 == "+14155550199" and lead.timezone == "America/Los_Angeles"


async def test_semicolon_and_bom(client: AsyncClient, admin_headers, campaign) -> None:
    csv_text = "﻿Business;Phone\nX;+63 2 8555 0100\n"
    r = (await _import(client, campaign, admin_headers, csv_text=csv_text)).json()
    assert r["headers"] == ["Business", "Phone"] and r["imported"] == 1


async def test_rep_cannot_import(client: AsyncClient, make_user, campaign) -> None:
    from tests.conftest import auth_header

    from app.crm.enums import UserRole

    rep = await make_user(UserRole.rep)
    assert (await _import(client, campaign, auth_header(rep))).status_code == 403
