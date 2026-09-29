from httpx import AsyncClient
from sqlalchemy import select
from tests.conftest import auth_header

from app.crm.enums import LeadStatus, Market, UserRole
from app.crm.models import AuditLog, Campaign, Lead, PlaybookVersion, SipTrunk
from app.learning.models import EvalRun, EvalScenario


def _body(client_id, **kw):
    return {
        "name": "YP SEO US",
        "client_id": str(client_id),
        "market": "US",
        "country_codes": ["us"],
        "default_timezone": "America/New_York",
        **kw,
    }


async def _trunk(db_session) -> SipTrunk:
    t = SipTrunk(name="Telnyx US", market=Market.US, caller_ids=["+13125550199"])
    db_session.add(t)
    await db_session.flush()
    return t


async def test_create_campaign_defaults_and_normalization(
    client: AsyncClient, admin_headers, yp_client, db_session
) -> None:
    trunk = await _trunk(db_session)
    r = await client.post(
        "/api/v1/campaigns",
        json=_body(
            yp_client.id,
            sip_trunk_id=str(trunk.id),
            caller_id="(312) 555-0199",
            test_allowlist=["312-555-0100", "+13125550100"],
        ),
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "draft" and c["test_mode"] is True
    assert c["country_codes"] == ["US"]
    assert c["caller_id"] == "+13125550199"
    assert c["test_allowlist"] == ["+13125550100"]
    assert c["calling_window"]["mon"] == [["09:00", "17:30"]] and "sat" not in c["calling_window"]
    assert c["compliance"]["ai_disclosure"] == "on_ask"
    assert c["appointment_settings"]["duration_min"] == 20
    assert c["requeue_no_show"] is False
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.action == "campaign.create"))
    assert audit is not None


async def test_campaign_validation(
    client: AsyncClient, admin_headers, yp_client, db_session
) -> None:
    async def post(**kw):
        return await client.post(
            "/api/v1/campaigns", json=_body(yp_client.id, **kw), headers=admin_headers
        )

    assert (await post(calling_window={"mon": [["07:30", "12:00"]]})).status_code == 422
    assert (await post(calling_window={"mon": [["09:00", "21:30"]]})).status_code == 422
    assert (await post(calling_window={"funday": [["09:00", "12:00"]]})).status_code == 422
    overlap = {"mon": [["09:00", "12:00"], ["11:00", "13:00"]]}
    assert (await post(calling_window=overlap)).status_code == 422
    assert (await post(default_timezone="Mars/Olympus")).status_code == 422
    assert (await post(concurrency=50)).status_code == 422
    assert (await post(test_allowlist=["not a phone"])).status_code == 422
    assert (await post(caller_id="+13125550199")).status_code == 422  # no trunk
    trunk = await _trunk(db_session)
    r = await post(sip_trunk_id=str(trunk.id), caller_id="+12125550100")  # not trunk's number
    assert r.status_code == 422
    assert (await post(compliance={"ai_disclosure": "never"})).status_code == 422


async def test_patch_campaign(client: AsyncClient, admin_headers, campaign) -> None:
    r = await client.patch(
        f"/api/v1/campaigns/{campaign.id}",
        json={"concurrency": 5, "compliance": {"ai_disclosure": "upfront"}, "daily_cap": None},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["concurrency"] == 5
    assert r.json()["compliance"]["ai_disclosure"] == "upfront"


async def _startable(db_session, campaign: Campaign) -> PlaybookVersion:
    trunk = await _trunk(db_session)
    pv = PlaybookVersion(campaign_id=campaign.id, version=1, playbook={"schema_version": "1.0"})
    db_session.add(pv)
    await db_session.flush()
    campaign.sip_trunk_id = trunk.id
    campaign.caller_id = "+13125550199"
    campaign.test_allowlist = ["+13125550100"]
    campaign.active_playbook_version_id = pv.id
    await db_session.flush()
    return pv


async def test_actions_lifecycle(client: AsyncClient, admin_headers, campaign, db_session) -> None:
    url = f"/api/v1/campaigns/{campaign.id}/actions"
    r = await client.post(f"{url}/start", headers=admin_headers)
    assert r.status_code == 409 and "playbook" in r.json()["detail"]

    await _startable(db_session, campaign)
    r = await client.post(f"{url}/start", headers=admin_headers)
    assert r.status_code == 200 and r.json()["status"] == "testing"
    # Switching test mode while running is refused.
    r = await client.patch(
        f"/api/v1/campaigns/{campaign.id}", json={"test_mode": False}, headers=admin_headers
    )
    assert r.status_code == 409
    assert (await client.post(f"{url}/pause", headers=admin_headers)).json()["status"] == "paused"
    r = await client.patch(
        f"/api/v1/campaigns/{campaign.id}", json={"test_mode": False}, headers=admin_headers
    )
    assert r.status_code == 200
    assert (await client.post(f"{url}/resume", headers=admin_headers)).json()["status"] == "active"
    r = await client.post(f"{url}/complete", headers=admin_headers)
    assert r.json()["status"] == "completed"
    assert (await client.post(f"{url}/resume", headers=admin_headers)).status_code == 409
    r = await client.patch(
        f"/api/v1/campaigns/{campaign.id}", json={"name": "x"}, headers=admin_headers
    )
    assert r.status_code == 409


async def test_clone_copies_playbook_inactive(
    client: AsyncClient, admin_headers, campaign, db_session
) -> None:
    await _startable(db_session, campaign)
    r = await client.post(f"/api/v1/campaigns/{campaign.id}/actions/clone", headers=admin_headers)
    assert r.status_code == 200, r.text
    clone = r.json()
    assert clone["id"] != str(campaign.id)
    assert clone["name"].endswith("(copy)") and clone["status"] == "draft"
    assert clone["active_playbook_version_id"] is None
    versions = (
        await client.get(f"/api/v1/campaigns/{clone['id']}/playbooks", headers=admin_headers)
    ).json()
    assert len(versions) == 1 and versions[0]["is_active"] is False


async def test_delete_only_draft(client: AsyncClient, admin_headers, campaign, db_session) -> None:
    campaign.status = "paused"
    await db_session.flush()
    r = await client.delete(f"/api/v1/campaigns/{campaign.id}", headers=admin_headers)
    assert r.status_code == 409


async def test_playbook_versions_and_activation_test_mode(
    client: AsyncClient, admin_headers, campaign, db_session
) -> None:
    url = f"/api/v1/campaigns/{campaign.id}/playbooks"
    v1 = (await client.post(url, json={"playbook": {"a": 1}}, headers=admin_headers)).json()
    v2 = (await client.post(url, json={"playbook": {"a": 2}}, headers=admin_headers)).json()
    assert (v1["version"], v2["version"]) == (1, 2)
    assert v1["is_active"] is False  # never auto-activated

    r = await client.post(f"{url}/{v1['id']}/activate", json={}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["is_active"] is True
    r = await client.post(f"{url}/{v2['id']}/activate", json={}, headers=admin_headers)
    assert r.status_code == 200
    rows = (await client.get(url, headers=admin_headers)).json()
    assert [(p["version"], p["is_active"]) for p in rows] == [(2, True), (1, False)]
    log = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "playbook.activate").order_by(AuditLog.ts.desc())
    )
    assert log is not None and log.after["version"] in (1, 2)


async def test_activation_gate_for_live_campaign(
    client: AsyncClient, make_user, campaign, db_session
) -> None:
    admin, manager = await make_user(UserRole.admin), await make_user(UserRole.manager)
    campaign.test_mode = False
    pv = PlaybookVersion(campaign_id=campaign.id, version=1, playbook={})
    db_session.add(pv)
    await db_session.flush()
    url = f"/api/v1/campaigns/{campaign.id}/playbooks/{pv.id}/activate"

    r = await client.post(url, json={}, headers=auth_header(manager))
    assert r.status_code == 409 and "eval gate" in r.json()["detail"]
    r = await client.post(url, json={"override_reason": "urgent"}, headers=auth_header(manager))
    assert r.status_code == 403

    # 9/10 pass but the compliance scenario fails → still blocked
    scenarios = [EvalScenario(campaign_id=campaign.id, persona={}) for _ in range(9)]
    compliance = EvalScenario(campaign_id=campaign.id, persona={"category": "compliance"})
    db_session.add_all([*scenarios, compliance])
    await db_session.flush()
    db_session.add_all(
        [
            EvalRun(campaign_id=campaign.id, playbook_version_id=pv.id, scenario_id=s.id,
                    passed=True)
            for s in scenarios
        ]
        + [EvalRun(campaign_id=campaign.id, playbook_version_id=pv.id,
                   scenario_id=compliance.id, passed=False)]
    )  # fmt: skip
    await db_session.flush()
    assert (await client.post(url, json={}, headers=auth_header(manager))).status_code == 409

    # Admin override is allowed and audit-logged.
    r = await client.post(url, json={"override_reason": "hotfix"}, headers=auth_header(admin))
    assert r.status_code == 200
    log = await db_session.scalar(select(AuditLog).where(AuditLog.action == "playbook.activate"))
    assert log.after["override_reason"] == "hotfix" and log.after["pass_rate"] == 0.9


# --- leads ------------------------------------------------------------------------------------


async def _lead(db_session, campaign, phone, status=LeadStatus.new) -> Lead:
    lead = Lead(campaign_id=campaign.id, phone_e164=phone, status=status, timezone="UTC")
    db_session.add(lead)
    await db_session.flush()
    return lead


async def test_manual_lead_create_and_list(client: AsyncClient, admin_headers, campaign) -> None:
    url = f"/api/v1/campaigns/{campaign.id}/leads"
    r = await client.post(
        url,
        json={"phone": "(604) 555-0100", "business_name": "Maple", "region": "BC"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["phone_e164"] == "+16045550100"
    assert r.json()["timezone"] == "America/Vancouver"
    dup = await client.post(url, json={"phone": "+1 604 555 0100"}, headers=admin_headers)
    assert dup.status_code == 409

    await client.post(url, json={"phone": "+13125550111", "business_name": "Zed"},
                      headers=admin_headers)  # fmt: skip
    page = (await client.get(url, params={"q": "map"}, headers=admin_headers)).json()
    assert page["total"] == 1 and page["items"][0]["business_name"] == "Maple"
    page = (await client.get(url, params={"q": "555-0111"}, headers=admin_headers)).json()
    assert page["total"] == 1
    page = (
        await client.get(url, params={"status": ["new"], "sort": "business_name"},
                         headers=admin_headers)
    ).json()  # fmt: skip
    assert [i["business_name"] for i in page["items"]] == ["Maple", "Zed"]


async def test_bulk_requeue_move_dnc_export(
    client: AsyncClient, admin_headers, campaign, yp_client, db_session
) -> None:
    a = await _lead(db_session, campaign, "+13125550121", LeadStatus.exhausted)
    b = await _lead(db_session, campaign, "+13125550122", LeadStatus.calling)
    c = await _lead(db_session, campaign, "+13125550123", LeadStatus.not_interested)

    r = await client.post(
        "/api/v1/leads/bulk",
        json={"ids": [str(a.id), str(b.id)], "action": "requeue"},
        headers=admin_headers,
    )
    body = r.json()
    assert body["updated"] == 1 and body["skipped"][0]["id"] == str(b.id)
    await db_session.refresh(a)
    assert a.status == LeadStatus.queued

    other = Campaign(client_id=yp_client.id, name="Other", market=Market.US,
                     default_timezone="America/New_York")  # fmt: skip
    db_session.add(other)
    await db_session.flush()
    await _lead(db_session, other, "+13125550123")  # c's phone already exists in target
    r = await client.post(
        "/api/v1/leads/bulk",
        json={"ids": [str(a.id), str(c.id)], "action": "move",
              "target_campaign_id": str(other.id)},
        headers=admin_headers,
    )  # fmt: skip
    body = r.json()
    assert body["updated"] == 1 and "target" in body["skipped"][0]["reason"]
    await db_session.refresh(a)
    assert a.campaign_id == other.id and a.status == LeadStatus.new and a.attempts == 0

    r = await client.post(
        "/api/v1/leads/bulk", json={"ids": [str(c.id)], "action": "dnc"}, headers=admin_headers
    )
    assert r.json()["updated"] == 1
    await db_session.refresh(c)
    assert c.status == LeadStatus.dnc
    # The same phone in the other campaign was moved to dnc too (global scope).
    same = await db_session.scalar(
        select(Lead).where(Lead.campaign_id == other.id, Lead.phone_e164 == "+13125550123")
    )
    await db_session.refresh(same)
    assert same.status == LeadStatus.dnc
    # DNC leads cannot be requeued.
    r = await client.post(
        "/api/v1/leads/bulk", json={"ids": [str(c.id)], "action": "requeue"},
        headers=admin_headers,
    )  # fmt: skip
    assert r.json()["updated"] == 0

    r = await client.post(
        "/api/v1/leads/bulk", json={"ids": [str(c.id)], "action": "export"}, headers=admin_headers
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "+13125550123" in r.text and r.text.lstrip("﻿").startswith("id,campaign_id")


async def test_lead_patch_and_timeline(
    client: AsyncClient, admin_headers, campaign, db_session
) -> None:
    lead = await _lead(db_session, campaign, "+13125550131")
    r = await client.patch(
        f"/api/v1/leads/{lead.id}",
        json={"notes": "call after lunch", "region": "CA", "country_code": "US"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "call after lunch"
    assert r.json()["timezone"] == "America/Los_Angeles"
    tl = (await client.get(f"/api/v1/leads/{lead.id}/timeline", headers=admin_headers)).json()
    assert {i["kind"] for i in tl} == {"created", "audit"}


async def test_dnc_add_check_and_idempotent(client: AsyncClient, admin_headers, campaign,
                                            db_session) -> None:  # fmt: skip
    lead = await _lead(db_session, campaign, "+13125550141")
    r1 = await client.post("/api/v1/dnc", json={"phone": "312 555 0141", "default_region": "US"},
                           headers=admin_headers)  # fmt: skip
    r2 = await client.post("/api/v1/dnc", json={"phone": "+13125550141"}, headers=admin_headers)
    assert r1.status_code == r2.status_code == 201 and r1.json()["id"] == r2.json()["id"]
    await db_session.refresh(lead)
    assert lead.status == LeadStatus.dnc
    r = await client.post(
        "/api/v1/dnc/check",
        json={"phones": ["+13125550141", "+13125550142", "nope"]},
        headers=admin_headers,
    )
    assert r.json() == {"results": {"+13125550141": True, "+13125550142": False},
                        "invalid": ["nope"]}  # fmt: skip
    r = await client.post(
        "/api/v1/dnc", json={"phone": "+13125550143", "scope": "client"}, headers=admin_headers
    )
    assert r.status_code == 422
