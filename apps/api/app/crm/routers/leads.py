import csv
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import String, cast, func, or_, select

from app.crm.audit import audit, snapshot
from app.crm.deps import AnyUser, DbSession, Manager
from app.crm.enums import CampaignStatus, DncScope, LeadSource, LeadStatus
from app.crm.models import (
    Appointment,
    AuditLog,
    CallAttempt,
    Campaign,
    ConsentEvent,
    Lead,
    LeadImport,
)
from app.crm.routers.campaigns import get_campaign
from app.crm.routers.dnc import add_dnc
from app.crm.schemas import (
    BulkAction,
    BulkResult,
    ImportReport,
    LeadCreate,
    LeadImportOut,
    LeadOut,
    LeadUpdate,
    Page,
    TimelineItem,
)
from app.crm.services.dnc import dnc_phones
from app.crm.services.lead_import import LeadImportError, build_lead_values, run_import
from app.dialer.state_machine import CampaignRules, InvalidTransition, ManualRequeue, transition
from maria_shared.phone import InvalidPhoneError

router = APIRouter(tags=["leads"])

SORTABLE = {
    "created_at": Lead.created_at,
    "business_name": Lead.business_name,
    "status": Lead.status,
    "attempts": Lead.attempts,
    "next_attempt_at": Lead.next_attempt_at,
    "priority": Lead.priority,
}


# --- import -----------------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/leads/import", response_model=ImportReport)
async def import_leads(
    campaign_id: uuid.UUID,
    session: DbSession,
    user: Manager,
    file: Annotated[UploadFile, File()],
    column_map: Annotated[str | None, Form()] = None,
    dry_run: Annotated[bool, Form()] = False,
) -> ImportReport:
    """CSV import. `column_map` is JSON {lead_field: csv_header}; omit it to get a suggested map.
    `dry_run=true` returns the same report without writing (wizard preview)."""
    campaign = await get_campaign(session, campaign_id)
    if campaign.status == CampaignStatus.completed:
        raise HTTPException(status.HTTP_409_CONFLICT, "campaign is completed")
    cmap: dict[str, str] | None = None
    if column_map:
        try:
            cmap = json.loads(column_map)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, "column_map must be JSON") from exc
        if not isinstance(cmap, dict) or not all(
            isinstance(k, str) and isinstance(v, str | None) for k, v in cmap.items()
        ):
            raise HTTPException(422, "column_map must be an object of {lead_field: csv_header}")
    data = await file.read()
    try:
        report = await run_import(
            session, campaign, data, file.filename, cmap, dry_run=dry_run, user=user
        )
    except LeadImportError as exc:
        raise HTTPException(422, str(exc)) from exc
    if dry_run:
        await session.rollback()
    else:
        audit(
            session, user, "lead.import", "lead_import", report.import_id,
            after={"campaign_id": str(campaign.id), "imported": report.imported,
                   "skipped_dupe": report.skipped_dupe, "skipped_dnc": report.skipped_dnc,
                   "skipped_invalid": report.skipped_invalid},
        )  # fmt: skip
        await session.commit()
    return report


@router.get("/campaigns/{campaign_id}/leads/imports", response_model=list[LeadImportOut])
async def list_imports(campaign_id: uuid.UUID, session: DbSession, _: AnyUser) -> list[LeadImport]:
    await get_campaign(session, campaign_id)
    return list(
        await session.scalars(
            select(LeadImport)
            .where(LeadImport.campaign_id == campaign_id)
            .order_by(LeadImport.created_at.desc())
            .limit(50)
        )
    )


# --- list / create ----------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/leads", response_model=Page[LeadOut])
async def list_leads(
    campaign_id: uuid.UUID,
    session: DbSession,
    _: AnyUser,
    status_: Annotated[list[LeadStatus] | None, Query(alias="status")] = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort: str = "-created_at",
) -> Page[LeadOut]:
    await get_campaign(session, campaign_id)
    stmt = select(Lead).where(Lead.campaign_id == campaign_id)
    if status_:
        stmt = stmt.where(Lead.status.in_(status_))
    if q:
        like = f"%{q.strip()}%"
        digits = "".join(c for c in q if c.isdigit())
        conds = [
            Lead.business_name.ilike(like),
            Lead.contact_name.ilike(like),
            Lead.email.ilike(like),
            Lead.city.ilike(like),
            Lead.external_id.ilike(like),
            cast(Lead.custom, String).ilike(like),
        ]
        if digits:
            conds.append(Lead.phone_e164.contains(digits))
        stmt = stmt.where(or_(*conds))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTABLE.get(sort.lstrip("-"), Lead.created_at)
    order = col.desc().nulls_last() if sort.startswith("-") else col.asc().nulls_last()
    rows = await session.scalars(
        stmt.order_by(order, Lead.id).offset((page - 1) * page_size).limit(page_size)
    )
    return Page[LeadOut](
        items=[LeadOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size
    )


def _fields(body: LeadCreate | LeadUpdate, lead: Lead | None = None) -> dict[str, Any]:
    """Raw field dict for build_lead_values, falling back to the lead's current values."""
    data = body.model_dump(exclude_unset=True)
    base: dict[str, Any] = {}
    if lead is not None:
        base = {c.key: getattr(lead, c.key) for c in Lead.__table__.columns}
        base["phone"] = lead.phone_e164
        base["phone_alt"] = lead.phone_alt_e164
    return base | data


@router.post("/campaigns/{campaign_id}/leads", response_model=LeadOut, status_code=201)
async def create_lead(
    campaign_id: uuid.UUID, body: LeadCreate, session: DbSession, user: Manager
) -> Lead:
    campaign = await get_campaign(session, campaign_id)
    fields = _fields(body)
    try:
        values = build_lead_values(campaign, fields, body.custom)
    except InvalidPhoneError as exc:
        raise HTTPException(422, f"phone: {exc}") from exc
    if body.timezone:
        values["timezone"] = body.timezone
    phone = values["phone_e164"]
    if phone in await dnc_phones(session, [phone], campaign.client_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "phone is on the DNC list")
    exists = await session.scalar(
        select(Lead.id).where(Lead.campaign_id == campaign.id, Lead.phone_e164 == phone)
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "a lead with this phone already exists")
    lead = Lead(**values, source=LeadSource.manual, priority=body.priority)
    session.add(lead)
    await session.flush()
    audit(session, user, "lead.create", "lead", lead.id, after=snapshot(lead))
    await session.commit()
    await session.refresh(lead)
    return lead


# --- single lead -------------------------------------------------------------------------------


async def _get_lead(session: DbSession, lead_id: uuid.UUID) -> Lead:
    lead = await session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "lead not found")
    return lead


@router.get("/leads/{lead_id}", response_model=LeadOut)
async def read_lead(lead_id: uuid.UUID, session: DbSession, _: AnyUser) -> Lead:
    return await _get_lead(session, lead_id)


@router.patch("/leads/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: uuid.UUID, body: LeadUpdate, session: DbSession, user: Manager
) -> Lead:
    lead = await _get_lead(session, lead_id)
    campaign = await get_campaign(session, lead.campaign_id)
    before = snapshot(lead)
    changes = body.model_dump(exclude_unset=True)
    address_keys = {"phone", "country_code", "region"}
    if address_keys & changes.keys():
        fields = _fields(body, lead)
        if "timezone" not in changes:
            fields.pop("timezone", None)  # re-infer from the new address/phone
        try:
            values = build_lead_values(campaign, fields, lead.custom)
        except InvalidPhoneError as exc:
            raise HTTPException(422, f"phone: {exc}") from exc
        if values["phone_e164"] != lead.phone_e164:
            if lead.status == LeadStatus.calling:
                raise HTTPException(status.HTTP_409_CONFLICT, "lead is on a call")
            clash = await session.scalar(
                select(Lead.id).where(
                    Lead.campaign_id == lead.campaign_id, Lead.phone_e164 == values["phone_e164"]
                )
            )
            if clash:
                raise HTTPException(status.HTTP_409_CONFLICT, "another lead has this phone")
            if values["phone_e164"] in await dnc_phones(
                session, [values["phone_e164"]], campaign.client_id
            ):
                raise HTTPException(status.HTTP_409_CONFLICT, "phone is on the DNC list")
            lead.phone_e164 = values["phone_e164"]
        lead.country_code = values["country_code"]
        if "timezone" not in changes:
            lead.timezone = values["timezone"]
    if "phone_alt" in changes:
        alt = build_lead_values(
            campaign, {"phone": lead.phone_e164, "phone_alt": changes["phone_alt"]}, {}
        )["phone_alt_e164"]
        lead.phone_alt_e164 = alt
    for k, v in changes.items():
        if k in ("phone", "phone_alt", "country_code"):
            continue
        if k == "custom" and v is None:
            continue
        if k == "priority" and v is None:
            continue
        setattr(lead, k, v)
    audit(session, user, "lead.update", "lead", lead.id, before, snapshot(lead))
    await session.commit()
    await session.refresh(lead)
    return lead


@router.get("/leads/{lead_id}/timeline", response_model=list[TimelineItem])
async def lead_timeline(lead_id: uuid.UUID, session: DbSession, _: AnyUser) -> list[TimelineItem]:
    lead = await _get_lead(session, lead_id)
    items = [
        TimelineItem(
            ts=lead.created_at,
            kind="created",
            title=f"Lead created ({lead.source.value})",
            data={"campaign_id": str(lead.campaign_id)},
        )
    ]
    for a in await session.scalars(select(CallAttempt).where(CallAttempt.lead_id == lead.id)):
        items.append(
            TimelineItem(
                ts=a.started_at or a.created_at,
                kind="call",
                title=f"Call #{a.attempt_no}: {(a.outcome or a.status).value}"
                + (f" → {a.disposition}" if a.disposition else ""),
                data={
                    "attempt_id": str(a.id),
                    "duration_sec": a.duration_sec,
                    "summary": a.summary,
                },
            )  # fmt: skip
        )
    for ap in await session.scalars(select(Appointment).where(Appointment.lead_id == lead.id)):
        items.append(
            TimelineItem(
                ts=ap.created_at,
                kind="appointment",
                title=f"Appointment {ap.status.value} for {ap.start_at.isoformat()}",
                data={"appointment_id": str(ap.id), "type": ap.type.value},
            )
        )
    for ce in await session.scalars(select(ConsentEvent).where(ConsentEvent.lead_id == lead.id)):
        items.append(TimelineItem(ts=ce.ts, kind="consent", title=ce.type.value))
    for log in await session.scalars(
        select(AuditLog).where(AuditLog.entity == "lead", AuditLog.entity_id == lead.id)
    ):
        if log.action == "lead.create":
            continue
        items.append(
            TimelineItem(ts=log.ts, kind="audit", title=log.action, data={"after": log.after or {}})
        )
    items.sort(key=lambda i: i.ts, reverse=True)
    return items


# --- bulk ----------------------------------------------------------------------------------

EXPORT_COLUMNS = [
    "id", "campaign_id", "status", "business_name", "contact_name", "contact_title", "phone_e164",
    "phone_alt_e164", "email", "address_line", "city", "region", "postal_code", "country_code",
    "timezone", "website", "industry", "attempts", "last_disposition", "next_attempt_at",
    "last_attempt_at", "priority", "notes", "external_id", "source", "custom", "created_at",
]  # fmt: skip


def _export_csv(leads: list[Lead]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_COLUMNS)
    for lead in leads:
        row = []
        for col in EXPORT_COLUMNS:
            v = getattr(lead, col)
            if col == "custom":
                v = json.dumps(v or {}, ensure_ascii=False)
            elif isinstance(v, datetime):
                v = v.isoformat()
            elif hasattr(v, "value"):
                v = v.value
            row.append("" if v is None else v)
        w.writerow(row)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Response(
        content="﻿" + buf.getvalue(),  # BOM so Excel opens UTF-8 correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="leads-{stamp}.csv"'},
    )


@router.post("/leads/bulk", response_model=BulkResult)
async def bulk_action(body: BulkAction, session: DbSession, user: Manager) -> Any:
    leads = list(await session.scalars(select(Lead).where(Lead.id.in_(body.ids))))
    found = {lead.id for lead in leads}
    skipped: list[dict[str, Any]] = [
        {"id": str(i), "reason": "not found"} for i in body.ids if i not in found
    ]
    if body.action == "export":
        return _export_csv(leads)

    campaigns = {
        c.id: c
        for c in await session.scalars(
            select(Campaign).where(Campaign.id.in_({lead.campaign_id for lead in leads}))
        )
    }
    now = datetime.now(UTC)
    updated = 0

    if body.action == "requeue":
        for lead in leads:
            c = campaigns[lead.campaign_id]
            rules = CampaignRules(c.max_attempts, c.retry_spacing_hours,
                                  c.voicemail_counts_as_attempt, c.requeue_no_show)  # fmt: skip
            try:
                t = transition(lead.status, lead.attempts, ManualRequeue(), rules, now)
            except InvalidTransition as exc:
                skipped.append({"id": str(lead.id), "reason": str(exc)})
                continue
            if t is None:
                continue
            before = {"status": lead.status.value}
            lead.status, lead.next_attempt_at = t.status, t.next_attempt_at
            audit(session, user, "lead.requeue", "lead", lead.id, before, {"status": t.status})
            updated += 1

    elif body.action == "move":
        target = await get_campaign(session, body.target_campaign_id)  # type: ignore[arg-type]
        if target.status == CampaignStatus.completed:
            raise HTTPException(status.HTTP_409_CONFLICT, "target campaign is completed")
        taken = set(
            await session.scalars(
                select(Lead.phone_e164).where(
                    Lead.campaign_id == target.id,
                    Lead.phone_e164.in_([lead.phone_e164 for lead in leads]),
                )
            )
        )
        blocked = await dnc_phones(session, [lead.phone_e164 for lead in leads], target.client_id)
        for lead in leads:
            reason = None
            if lead.campaign_id == target.id:
                reason = "already in target campaign"
            elif lead.status in (LeadStatus.calling, LeadStatus.dnc):
                reason = f"lead is {lead.status.value}"
            elif lead.phone_e164 in taken:
                reason = "phone already exists in target campaign"
            elif lead.phone_e164 in blocked:
                reason = "phone is on the target client's DNC list"
            if reason:
                skipped.append({"id": str(lead.id), "reason": reason})
                continue
            before = {"campaign_id": str(lead.campaign_id), "status": lead.status.value}
            taken.add(lead.phone_e164)
            lead.campaign_id = target.id
            lead.status = LeadStatus.new
            lead.attempts = 0
            lead.next_attempt_at = None
            lead.last_disposition = None
            audit(session, user, "lead.move", "lead", lead.id, before,
                  {"campaign_id": str(target.id), "status": "new"})  # fmt: skip
            updated += 1

    elif body.action == "dnc":
        for lead in leads:
            await add_dnc(
                session, lead.phone_e164, DncScope.global_, None,
                body.reason or "bulk action", "crm_bulk", user,
            )  # fmt: skip
            await session.refresh(lead)
            if lead.status == LeadStatus.calling:
                skipped.append(
                    {"id": str(lead.id), "reason": "on a call; DNC applies after the call ends"}
                )
                continue
            audit(session, user, "lead.dnc", "lead", lead.id, None, {"status": "dnc"})
            updated += 1

    await session.commit()
    return BulkResult(action=body.action, updated=updated, skipped=skipped)
