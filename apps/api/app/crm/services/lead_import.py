"""CSV lead import: column mapping, E.164 normalization, dedupe, DNC skip, report (FR-L1/L2/L3).

One code path serves the wizard's preview (`dry_run=True`) and the real import.
"""

import csv
import io
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.enums import LeadSource, LeadStatus, Market
from app.crm.models import Campaign, Lead, LeadImport, User
from app.crm.schemas import ImportReport, ImportRowIssue
from app.crm.services.dnc import dnc_phones
from maria_shared.phone import InvalidPhoneError, normalize_phone, region_of
from maria_shared.timezone import infer_timezone, is_valid_timezone

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 50_000
MAX_STORED_ERRORS = 500
PREVIEW_ROWS = 20

# Lead fields a CSV column can map to. "phone" is required.
LEAD_FIELDS = (
    "phone",
    "phone_alt",
    "external_id",
    "business_name",
    "contact_name",
    "contact_title",
    "email",
    "address_line",
    "city",
    "region",
    "postal_code",
    "country_code",
    "timezone",
    "website",
    "industry",
    "notes",
)

# Normalized header → lead field, for the suggested mapping.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "phone": ("phone", "phonenumber", "phone1", "mainphone", "telephone", "tel", "mobile",
              "number", "contactnumber", "businessphone", "primaryphone"),
    "phone_alt": ("phone2", "altphone", "alternatephone", "secondaryphone", "otherphone"),
    "external_id": ("id", "externalid", "leadid", "recordid", "vendorid"),
    "business_name": ("businessname", "company", "companyname", "business", "organization",
                      "organisation", "account", "accountname"),
    "contact_name": ("contactname", "name", "fullname", "contact", "owner", "ownername",
                     "firstname"),
    "contact_title": ("title", "contacttitle", "jobtitle", "position", "role"),
    "email": ("email", "emailaddress", "mail"),
    "address_line": ("address", "addressline", "address1", "street", "streetaddress"),
    "city": ("city", "town", "municipality"),
    "region": ("state", "province", "region", "stateprovince", "stateorprovince", "st"),
    "postal_code": ("zip", "zipcode", "postalcode", "postcode", "postal"),
    "country_code": ("country", "countrycode", "cc"),
    "timezone": ("timezone", "tz", "timezoneiana"),
    "website": ("website", "url", "web", "site", "domain"),
    "industry": ("industry", "category", "vertical", "businesstype", "niche"),
    "notes": ("notes", "note", "comments", "comment"),
}  # fmt: skip

_COUNTRY_NAMES = {
    "USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US", "AMERICA": "US",
    "CANADA": "CA", "CAN": "CA", "PHILIPPINES": "PH", "PHL": "PH", "THE PHILIPPINES": "PH",
}  # fmt: skip


class LeadImportError(ValueError):
    """Raised for problems with the file itself (encoding, size, missing phone mapping)."""


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.lower())


def suggest_column_map(headers: list[str]) -> dict[str, str]:
    """{lead_field: csv_header} best guess."""
    out: dict[str, str] = {}
    normalized = {h: _norm_header(h) for h in headers}
    for fld, names in _SYNONYMS.items():
        for name in names:
            match = next((h for h, n in normalized.items() if n == name), None)
            if match and match not in out.values():
                out[fld] = match
                break
    return out


def _country(raw: str | None) -> str | None:
    if not raw:
        return None
    v = raw.strip().upper()
    v = _COUNTRY_NAMES.get(v, v)
    return v if re.fullmatch(r"[A-Z]{2}", v) else None


def decode_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    if len(data) > MAX_BYTES:
        raise LeadImportError(f"file too large (max {MAX_BYTES // (1024 * 1024)} MB)")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes almost anything
        raise LeadImportError("could not decode file (use UTF-8)")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [h.strip() for h in (reader.fieldnames or []) if h is not None]
    if not headers:
        raise LeadImportError("CSV has no header row")
    reader.fieldnames = headers
    rows: list[dict[str, str]] = []
    for row in reader:
        if len(rows) >= MAX_ROWS:
            raise LeadImportError(f"too many rows (max {MAX_ROWS})")
        clean = {k: (v or "").strip() for k, v in row.items() if k is not None}
        if any(clean.values()):
            rows.append(clean)
    return headers, rows


@dataclass
class _Result:
    imported: int = 0
    dupes: int = 0
    dnc: int = 0
    invalid: int = 0
    issues: list[ImportRowIssue] = field(default_factory=list)
    preview: list[dict[str, Any]] = field(default_factory=list)
    to_insert: list[dict[str, Any]] = field(default_factory=list)


def default_region(campaign: Campaign) -> str | None:
    if campaign.country_codes:
        return campaign.country_codes[0]
    return None if campaign.market == Market.OTHER else campaign.market.value


def build_lead_values(
    campaign: Campaign, fields: dict[str, str | None], custom: dict[str, Any]
) -> dict[str, Any]:
    """Normalize one lead's raw values. Raises InvalidPhoneError for a bad primary phone."""
    country = _country(fields.get("country_code"))
    region_default = country or default_region(campaign)
    phone = normalize_phone(fields.get("phone"), region_default)
    alt = None
    if fields.get("phone_alt"):
        try:
            alt = normalize_phone(fields["phone_alt"], region_default)
        except InvalidPhoneError:
            alt = None
    country = country or region_of(phone)
    tz = fields.get("timezone")
    if not is_valid_timezone(tz):
        tz = infer_timezone(
            phone,
            country=country,
            region=fields.get("region"),
            fallback=campaign.default_timezone,
        )
    email = (fields.get("email") or "").strip().lower() or None

    def val(k: str) -> str | None:
        v = fields.get(k)
        return v.strip() if v and v.strip() else None

    return {
        "campaign_id": campaign.id,
        "phone_e164": phone,
        "phone_alt_e164": alt if alt != phone else None,
        "external_id": val("external_id"),
        "business_name": val("business_name"),
        "contact_name": val("contact_name"),
        "contact_title": val("contact_title"),
        "email": email,
        "address_line": val("address_line"),
        "city": val("city"),
        "region": val("region"),
        "postal_code": val("postal_code"),
        "country_code": country,
        "timezone": tz,
        "website": val("website"),
        "industry": val("industry"),
        "notes": val("notes"),
        "custom": custom,
    }


async def run_import(
    session: AsyncSession,
    campaign: Campaign,
    data: bytes,
    filename: str | None,
    column_map: dict[str, str] | None,
    dry_run: bool,
    user: User | None,
) -> ImportReport:
    headers, rows = decode_csv(data)
    suggested = suggest_column_map(headers)
    cmap = dict(column_map) if column_map is not None else suggested

    unknown_fields = set(cmap) - set(LEAD_FIELDS)
    if unknown_fields:
        raise LeadImportError(f"unknown lead fields in column_map: {sorted(unknown_fields)}")
    missing_headers = {h for h in cmap.values() if h and h not in headers}
    if missing_headers:
        raise LeadImportError(
            f"column_map refers to missing CSV columns: {sorted(missing_headers)}"
        )
    cmap = {k: v for k, v in cmap.items() if v}
    if "phone" not in cmap:
        raise LeadImportError("map a CSV column to 'phone' (required)")

    mapped_headers = set(cmap.values())
    custom_headers = [h for h in headers if h not in mapped_headers]

    res = _Result()
    normalized: list[tuple[int, dict[str, Any]]] = []
    for i, row in enumerate(rows, start=1):
        fields = {fld: row.get(h) for fld, h in cmap.items()}
        custom = {h: row[h] for h in custom_headers if row.get(h)}
        try:
            values = build_lead_values(campaign, fields, custom)
        except InvalidPhoneError as exc:
            res.invalid += 1
            res.issues.append(
                ImportRowIssue(row=i, reason="invalid", detail=str(exc), value=fields.get("phone"))
            )
            continue
        normalized.append((i, values))

    phones = [v["phone_e164"] for _, v in normalized]
    existing = set()
    for start in range(0, len(phones), 5000):
        existing.update(
            await session.scalars(
                select(Lead.phone_e164).where(
                    Lead.campaign_id == campaign.id,
                    Lead.phone_e164.in_(phones[start : start + 5000]),
                )
            )
        )
    alt_phones = [v["phone_alt_e164"] for _, v in normalized if v["phone_alt_e164"]]
    blocked = await dnc_phones(session, phones + alt_phones, campaign.client_id)

    seen: set[str] = set()
    for i, values in normalized:
        phone = values["phone_e164"]
        status = "ok"
        if phone in blocked:
            res.dnc += 1
            status = "dnc"
            res.issues.append(
                ImportRowIssue(row=i, reason="dnc", detail="phone is on the DNC list", value=phone)
            )
        elif phone in seen or phone in existing:
            res.dupes += 1
            status = "duplicate"
            detail = "duplicate within file" if phone in seen else "already in this campaign"
            res.issues.append(ImportRowIssue(row=i, reason="duplicate", detail=detail, value=phone))
        else:
            if values["phone_alt_e164"] in blocked:
                values["phone_alt_e164"] = None
            res.to_insert.append(values)
        seen.add(phone)
        if len(res.preview) < PREVIEW_ROWS:
            res.preview.append({"row": i, "status": status, **_preview(values)})

    import_id: uuid.UUID | None = None
    if dry_run:
        res.imported = len(res.to_insert)
    else:
        for start in range(0, len(res.to_insert), 1000):
            chunk = [
                {**v, "source": LeadSource.csv, "status": LeadStatus.new}
                for v in res.to_insert[start : start + 1000]
            ]
            inserted = await session.scalars(
                insert(Lead)
                .values(chunk)
                .on_conflict_do_nothing(index_elements=["campaign_id", "phone_e164"])
                .returning(Lead.id)
            )
            n = len(inserted.all())
            res.imported += n
            res.dupes += len(chunk) - n  # lost a race with a concurrent import
        record = LeadImport(
            campaign_id=campaign.id,
            filename=filename,
            row_count=len(rows),
            imported=res.imported,
            skipped_dupe=res.dupes,
            skipped_dnc=res.dnc,
            errors=[x.model_dump() for x in res.issues[:MAX_STORED_ERRORS]],
            column_map=cmap,
            created_by=user.id if user else None,
        )
        session.add(record)
        await session.flush()
        import_id = record.id

    return ImportReport(
        import_id=import_id,
        dry_run=dry_run,
        filename=filename,
        headers=headers,
        column_map=cmap,
        suggested_column_map=suggested,
        row_count=len(rows),
        imported=res.imported,
        skipped_dupe=res.dupes,
        skipped_dnc=res.dnc,
        skipped_invalid=res.invalid,
        issues=res.issues[:MAX_STORED_ERRORS],
        preview=res.preview,
    )


def _preview(values: dict[str, Any]) -> dict[str, Any]:
    keys = ("phone_e164", "business_name", "contact_name", "city", "region", "country_code",
            "timezone")  # fmt: skip
    return {k: values.get(k) for k in keys}
