import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.crm.audit import audit, snapshot
from app.crm.deps import AnyUser, DbSession, Manager
from app.crm.enums import CampaignStatus, Market, UserRole
from app.crm.models import Campaign, Client, Lead, PlaybookVersion, SipTrunk
from app.crm.schemas import (
    ActivateIn,
    CampaignCreate,
    CampaignOut,
    CampaignUpdate,
    PlaybookIn,
    PlaybookOut,
)
from app.learning.models import EvalRun, EvalScenario
from maria_shared.phone import InvalidPhoneError, normalize_phone

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

EVAL_PASS_RATE = 0.90  # 05 §2.4: ≥ 90 % and all compliance scenarios pass


def _unprocessable(msg: str) -> HTTPException:
    return HTTPException(422, msg)


def _conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)


async def get_campaign(session: DbSession, campaign_id: uuid.UUID) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "campaign not found")
    return campaign


def _region(market: Market, country_codes: list[str]) -> str | None:
    if country_codes:
        return country_codes[0]
    return None if market == Market.OTHER else market.value


async def _validate(session: DbSession, data: dict[str, Any]) -> dict[str, Any]:
    """Cross-field/DB checks on a full (merged) campaign dict; normalizes phone numbers."""
    if await session.get(Client, data["client_id"]) is None:
        raise _unprocessable("client not found")
    region = _region(data["market"], data["country_codes"])

    allow: list[str] = []
    for n in data.get("test_allowlist") or []:
        try:
            e164 = normalize_phone(n, region)
        except InvalidPhoneError as exc:
            raise _unprocessable(f"test_allowlist {n!r}: {exc}") from exc
        if e164 not in allow:
            allow.append(e164)
    data["test_allowlist"] = allow

    trunk = None
    if data.get("sip_trunk_id"):
        trunk = await session.get(SipTrunk, data["sip_trunk_id"])
        if trunk is None:
            raise _unprocessable("sip trunk not found")
    if data.get("caller_id"):
        try:
            data["caller_id"] = normalize_phone(data["caller_id"], region)
        except InvalidPhoneError as exc:
            raise _unprocessable(f"caller_id: {exc}") from exc
        if trunk is None:
            raise _unprocessable("caller_id requires a sip trunk")
        if data["caller_id"] not in trunk.caller_ids:
            raise _unprocessable("caller_id must be one of the trunk's caller_ids")
    return data


async def _lead_counts(
    session: DbSession, campaign_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    out: dict[uuid.UUID, dict[str, int]] = {c: {} for c in campaign_ids}
    rows = await session.execute(
        select(Lead.campaign_id, Lead.status, func.count())
        .where(Lead.campaign_id.in_(campaign_ids))
        .group_by(Lead.campaign_id, Lead.status)
    )
    for cid, st, n in rows:
        out[cid][st.value] = n
    return out


async def _out(session: DbSession, campaign: Campaign) -> CampaignOut:
    out = CampaignOut.model_validate(campaign)
    out.lead_counts = (await _lead_counts(session, [campaign.id]))[campaign.id]
    return out


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(session: DbSession, _: AnyUser) -> list[CampaignOut]:
    campaigns = list(await session.scalars(select(Campaign).order_by(Campaign.created_at.desc())))
    counts = await _lead_counts(session, [c.id for c in campaigns])
    result = []
    for c in campaigns:
        out = CampaignOut.model_validate(c)
        out.lead_counts = counts[c.id]
        result.append(out)
    return result


@router.post("", response_model=CampaignOut, status_code=201)
async def create_campaign(body: CampaignCreate, session: DbSession, user: Manager) -> CampaignOut:
    data = await _validate(session, body.model_dump(mode="python"))
    data["appointment_settings"] = body.appointment_settings.model_dump(mode="json")
    data["compliance"] = body.compliance.model_dump(mode="json")
    campaign = Campaign(**data, status=CampaignStatus.draft, created_by=user.id)
    session.add(campaign)
    await session.flush()
    audit(session, user, "campaign.create", "campaign", campaign.id, after=snapshot(campaign))
    await session.commit()
    await session.refresh(campaign)
    return await _out(session, campaign)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def read_campaign(campaign_id: uuid.UUID, session: DbSession, _: AnyUser) -> CampaignOut:
    return await _out(session, await get_campaign(session, campaign_id))


EDITABLE = set(CampaignUpdate.model_fields)
NULLABLE = {"sip_trunk_id", "caller_id", "daily_cap", "daily_budget_usd"}


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID, body: CampaignUpdate, session: DbSession, user: Manager
) -> CampaignOut:
    campaign = await get_campaign(session, campaign_id)
    if campaign.status == CampaignStatus.completed:
        raise _conflict("completed campaigns are read-only; clone it instead")
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if v is not None or k in NULLABLE
    }
    for k in ("appointment_settings", "compliance"):
        if k in changes:
            changes[k] = getattr(body, k).model_dump(mode="json")
    running = campaign.status in (CampaignStatus.testing, CampaignStatus.active)
    if running and "test_mode" in changes and changes["test_mode"] != campaign.test_mode:
        raise _conflict("pause the campaign before switching test mode")
    before = snapshot(campaign)
    merged = {k: getattr(campaign, k) for k in EDITABLE} | changes
    merged = await _validate(session, merged)
    for k in changes:
        setattr(campaign, k, merged[k])
    audit(session, user, "campaign.update", "campaign", campaign.id, before, snapshot(campaign))
    await session.commit()
    await session.refresh(campaign)
    return await _out(session, campaign)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: uuid.UUID, session: DbSession, user: Manager) -> None:
    campaign = await get_campaign(session, campaign_id)
    if campaign.status != CampaignStatus.draft:
        raise _conflict("only draft campaigns can be deleted; use 'complete' to archive")
    audit(session, user, "campaign.delete", "campaign", campaign.id, before=snapshot(campaign))
    await session.delete(campaign)
    await session.commit()


# --- actions ---------------------------------------------------------------------------------

Action = Literal["start", "pause", "resume", "complete", "clone"]


def _check_startable(campaign: Campaign) -> None:
    problems = []
    if campaign.active_playbook_version_id is None:
        problems.append("activate a playbook version")
    if campaign.sip_trunk_id is None or not campaign.caller_id:
        problems.append("set a SIP trunk and caller ID")
    if campaign.test_mode and not campaign.test_allowlist:
        problems.append("add at least one number to the test allowlist")
    if problems:
        raise _conflict("cannot start: " + "; ".join(problems))


@router.post("/{campaign_id}/actions/{action}", response_model=CampaignOut)
async def campaign_action(
    campaign_id: uuid.UUID, action: Action, session: DbSession, user: Manager
) -> CampaignOut:
    campaign = await get_campaign(session, campaign_id)
    if action == "clone":
        return await _clone(session, campaign, user)

    before = snapshot(campaign, ["status"])
    current = campaign.status
    running_status = CampaignStatus.testing if campaign.test_mode else CampaignStatus.active
    if action == "start":
        if current not in (CampaignStatus.draft, CampaignStatus.testing):
            raise _conflict(f"cannot start a campaign that is {current.value}")
        if current == CampaignStatus.testing and campaign.test_mode:
            raise _conflict("already testing; turn off test mode (while paused) to go live")
        _check_startable(campaign)
        campaign.status = running_status
    elif action == "pause":
        if current not in (CampaignStatus.testing, CampaignStatus.active):
            raise _conflict(f"cannot pause a campaign that is {current.value}")
        campaign.status = CampaignStatus.paused
    elif action == "resume":
        if current != CampaignStatus.paused:
            raise _conflict(f"cannot resume a campaign that is {current.value}")
        _check_startable(campaign)
        campaign.status = running_status
    elif action == "complete":
        if current == CampaignStatus.completed:
            raise _conflict("campaign already completed")
        campaign.status = CampaignStatus.completed
    audit(
        session, user, f"campaign.{action}", "campaign", campaign.id, before,
        snapshot(campaign, ["status"]),
    )  # fmt: skip
    await session.commit()
    await session.refresh(campaign)
    return await _out(session, campaign)


CLONE_SKIP = {
    "id",
    "created_at",
    "updated_at",
    "status",
    "active_playbook_version_id",
    "created_by",
}


async def _clone(session: DbSession, source: Campaign, user) -> CampaignOut:
    data = {
        c.key: getattr(source, c.key) for c in Campaign.__table__.columns if c.key not in CLONE_SKIP
    }
    data["name"] = f"{source.name} (copy)"
    data["test_mode"] = True
    clone = Campaign(**data, status=CampaignStatus.draft, created_by=user.id)
    session.add(clone)
    await session.flush()
    if source.active_playbook_version_id:
        pv = await session.get(PlaybookVersion, source.active_playbook_version_id)
        if pv is not None:
            # Copied as an inactive draft: activation is always a human action.
            session.add(
                PlaybookVersion(
                    campaign_id=clone.id,
                    version=1,
                    playbook=pv.playbook,
                    json_schema_version=pv.json_schema_version,
                    notes=f"cloned from {source.name} v{pv.version}",
                    source=pv.source,
                    created_by=user.id,
                    is_active=False,
                )
            )
    audit(session, user, "campaign.clone", "campaign", clone.id, {"source_id": str(source.id)})
    await session.commit()
    await session.refresh(clone)
    return await _out(session, clone)


# --- playbooks --------------------------------------------------------------------------------


@router.get("/{campaign_id}/playbooks", response_model=list[PlaybookOut])
async def list_playbooks(
    campaign_id: uuid.UUID, session: DbSession, _: AnyUser
) -> list[PlaybookVersion]:
    await get_campaign(session, campaign_id)
    return list(
        await session.scalars(
            select(PlaybookVersion)
            .where(PlaybookVersion.campaign_id == campaign_id)
            .order_by(PlaybookVersion.version.desc())
        )
    )


@router.post("/{campaign_id}/playbooks", response_model=PlaybookOut, status_code=201)
async def create_playbook(
    campaign_id: uuid.UUID, body: PlaybookIn, session: DbSession, user: Manager
) -> PlaybookVersion:
    """Save a new (inactive) playbook version. Full schema validation arrives in Phase 2."""
    campaign = await get_campaign(session, campaign_id)
    # Serialize version numbering per campaign.
    await session.execute(select(Campaign.id).where(Campaign.id == campaign.id).with_for_update())
    latest = await session.scalar(
        select(func.max(PlaybookVersion.version)).where(PlaybookVersion.campaign_id == campaign.id)
    )
    pv = PlaybookVersion(
        campaign_id=campaign.id,
        version=(latest or 0) + 1,
        playbook=body.playbook,
        json_schema_version=str(body.playbook.get("schema_version") or "") or None,
        notes=body.notes,
        source=body.source,
        created_by=user.id,
    )
    session.add(pv)
    await session.commit()
    await session.refresh(pv)
    return pv


async def eval_pass_rate(session: DbSession, version_id: uuid.UUID) -> tuple[float | None, bool]:
    """(pass rate over the latest run per scenario, all compliance scenarios passed)."""
    runs = (
        await session.execute(
            select(EvalRun, EvalScenario)
            .outerjoin(EvalScenario, EvalScenario.id == EvalRun.scenario_id)
            .where(EvalRun.playbook_version_id == version_id)
            .order_by(EvalRun.created_at.desc())
        )
    ).all()
    latest: dict[Any, tuple[EvalRun, EvalScenario | None]] = {}
    for run, scenario in runs:
        latest.setdefault(run.scenario_id or run.id, (run, scenario))
    if not latest:
        return None, False
    passed = sum(1 for run, _ in latest.values() if run.passed)
    compliance_ok = all(
        run.passed
        for run, scenario in latest.values()
        if scenario is not None and (scenario.persona or {}).get("category") == "compliance"
    )
    return passed / len(latest), compliance_ok


@router.post("/{campaign_id}/playbooks/{version_id}/activate", response_model=PlaybookOut)
async def activate_playbook(
    campaign_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ActivateIn,
    session: DbSession,
    user: Manager,
) -> PlaybookVersion:
    campaign = await get_campaign(session, campaign_id)
    pv = await session.get(PlaybookVersion, version_id)
    if pv is None or pv.campaign_id != campaign.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "playbook version not found")

    gate: dict[str, Any] = {"test_mode": campaign.test_mode}
    if not campaign.test_mode:
        rate, compliance_ok = await eval_pass_rate(session, pv.id)
        gate |= {"pass_rate": rate, "compliance_ok": compliance_ok}
        if rate is None or rate < EVAL_PASS_RATE or not compliance_ok:
            if not body.override_reason:
                raise _conflict(
                    f"eval gate not met (pass rate {rate if rate is not None else 'n/a'}, "
                    f"need ≥ {EVAL_PASS_RATE:.0%} and all compliance scenarios passing)"
                )
            if user.role != UserRole.admin:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "only admins can override")
            gate["override_reason"] = body.override_reason

    previous = campaign.active_playbook_version_id
    others = await session.scalars(
        select(PlaybookVersion).where(
            PlaybookVersion.campaign_id == campaign.id, PlaybookVersion.is_active.is_(True)
        )
    )
    for other in others:
        other.is_active = False
    pv.is_active = True
    campaign.active_playbook_version_id = pv.id
    audit(
        session, user, "playbook.activate", "playbook_version", pv.id,
        {"previous_version_id": str(previous) if previous else None},
        {"version": pv.version, **gate},
    )  # fmt: skip
    await session.commit()
    await session.refresh(pv)
    return pv
