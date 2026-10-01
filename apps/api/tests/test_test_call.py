"""POST /campaigns/{id}/test-call guards (CLAUDE.md: test_mode ⇒ allowlist only)."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from tests.conftest import PHONE, auth_header

from app.crm.enums import AttemptStatus, DncScope, LeadStatus, UserRole
from app.crm.models import CallAttempt, DncEntry
from app.dialer.livekit_client import get_dispatcher


class FakeDispatcher:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail

    async def dispatch(self, room: str, metadata: dict[str, Any]) -> str:
        if self.fail:
            raise RuntimeError("livekit down")
        self.calls.append((room, metadata))
        return "AD_test"


@pytest.fixture
def dispatcher():
    from app.main import app

    fake = FakeDispatcher()
    app.dependency_overrides[get_dispatcher] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_dispatcher, None)


def url(campaign) -> str:
    return f"/api/v1/campaigns/{campaign.id}/test-call"


async def test_test_call_dispatches(
    client: AsyncClient, admin_headers, ready_campaign, lead, dispatcher, db_session
) -> None:
    r = await client.post(
        url(ready_campaign), json={"lead_id": str(lead.id)}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    out = r.json()
    room, md = dispatcher.calls[0]
    assert room == out["room"] == f"call-{out['attempt_id']}"
    assert md["phone"] == PHONE and md["trunk_id"] == "ST_test"
    assert md["caller_id"] == "+12014621616" and md["test"] is True
    assert md["playbook_version_id"] == str(ready_campaign.active_playbook_version_id)
    await db_session.refresh(lead)
    assert lead.status == LeadStatus.calling
    attempt = await db_session.get(CallAttempt, out["attempt_id"])
    assert attempt.status == AttemptStatus.dialing and attempt.attempt_no == 1

    # Second call while the first is in progress is refused (never dial a lead twice at once).
    r = await client.post(
        url(ready_campaign), json={"lead_id": str(lead.id)}, headers=admin_headers
    )
    assert r.status_code == 409 and len(dispatcher.calls) == 1

    # The call read endpoint shows the attempt.
    r = await client.get(f"/api/v1/calls/{out['attempt_id']}", headers=admin_headers)
    assert r.status_code == 200 and r.json()["lead"]["status"] == "calling"


async def test_test_call_redial_after_finished_call(
    client: AsyncClient, admin_headers, ready_campaign, lead, dispatcher, db_session
) -> None:
    lead.status = LeadStatus.appointment_set
    await db_session.flush()
    r = await client.post(
        url(ready_campaign), json={"lead_id": str(lead.id)}, headers=admin_headers
    )
    assert r.status_code == 200, r.text


async def test_refused_when_phone_not_in_allowlist(
    client: AsyncClient, admin_headers, ready_campaign, lead, dispatcher, db_session
) -> None:
    ready_campaign.test_allowlist = ["+12125550199"]
    await db_session.flush()
    r = await client.post(
        url(ready_campaign), json={"lead_id": str(lead.id)}, headers=admin_headers
    )
    assert r.status_code == 409 and "allowlist" in r.json()["detail"]
    assert dispatcher.calls == []
    assert await db_session.scalar(select(CallAttempt.id)) is None


async def test_refused_when_not_test_mode(
    client: AsyncClient, admin_headers, ready_campaign, lead, dispatcher, db_session
) -> None:
    ready_campaign.test_mode = False
    await db_session.flush()
    r = await client.post(
        url(ready_campaign), json={"lead_id": str(lead.id)}, headers=admin_headers
    )
    assert r.status_code == 409 and "test mode" in r.json()["detail"]
    assert dispatcher.calls == []


async def test_refused_when_dnc(
    client: AsyncClient, admin_headers, ready_campaign, lead, dispatcher, db_session
) -> None:
    db_session.add(DncEntry(phone_e164=PHONE, scope=DncScope.global_, source="test"))
    await db_session.flush()
    r = await client.post(
        url(ready_campaign), json={"lead_id": str(lead.id)}, headers=admin_headers
    )
    assert r.status_code == 409 and "DNC" in r.json()["detail"]


async def test_refused_without_trunk_or_playbook(
    client: AsyncClient, admin_headers, ready_campaign, lead, dispatcher, db_session
) -> None:
    ready_campaign.active_playbook_version_id = None
    await db_session.flush()
    r = await client.post(
        url(ready_campaign), json={"lead_id": str(lead.id)}, headers=admin_headers
    )
    assert r.status_code == 409 and "playbook" in r.json()["detail"]


async def test_roles(client: AsyncClient, make_user, ready_campaign, lead, dispatcher) -> None:
    rep = auth_header(await make_user(UserRole.rep))
    r = await client.post(url(ready_campaign), json={"lead_id": str(lead.id)}, headers=rep)
    assert r.status_code == 403


async def test_dispatch_failure_releases_lead(
    client: AsyncClient, admin_headers, ready_campaign, lead, db_session
) -> None:
    from app.main import app

    app.dependency_overrides[get_dispatcher] = lambda: FakeDispatcher(fail=True)
    try:
        r = await client.post(
            url(ready_campaign), json={"lead_id": str(lead.id)}, headers=admin_headers
        )
    finally:
        app.dependency_overrides.pop(get_dispatcher, None)
    assert r.status_code == 502
    await db_session.refresh(lead)
    assert lead.status == LeadStatus.queued and lead.attempts == 0
    attempt = await db_session.scalar(select(CallAttempt))
    assert attempt.status == AttemptStatus.failed and attempt.end_reason == "dispatch_failed"
