"""Pydantic request/response schemas for the CRM API."""

import re
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.crm.enums import (
    AppointmentType,
    CampaignStatus,
    DncScope,
    LeadSource,
    LeadStatus,
    Market,
    PlaybookSource,
    UserRole,
)
from maria_shared.timezone import is_valid_timezone

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL_RE.match(v):
        raise ValueError("not a valid email address")
    return v


# Deliberately loose (allows internal domains like admin@altria.local).
EmailStr = Annotated[str, AfterValidator(_email)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def _check_tz(v: str | None) -> str | None:
    if v is not None and not is_valid_timezone(v):
        raise ValueError(f"unknown timezone {v!r}")
    return v


# --- auth / users ---------------------------------------------------------------------------


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: UserRole
    client_id: uuid.UUID | None
    is_active: bool
    created_at: datetime


class TokenOut(BaseModel):
    token: str
    user: UserOut


class UserCreate(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=8, max_length=72)]
    full_name: str | None = None
    role: UserRole
    client_id: uuid.UUID | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    client_id: uuid.UUID | None = None
    is_active: bool | None = None
    password: Annotated[str, StringConstraints(min_length=8, max_length=72)] | None = None


# --- clients --------------------------------------------------------------------------------


class ClientIn(BaseModel):
    name: NonEmpty
    contact_email: EmailStr | None = None
    notes: str | None = None
    is_active: bool = True


class ClientOut(ORM):
    id: uuid.UUID
    name: str
    contact_email: str | None
    notes: str | None
    is_active: bool


# --- sip trunks -----------------------------------------------------------------------------


class SipTrunkIn(BaseModel):
    name: NonEmpty
    market: Market
    livekit_trunk_id: str | None = None
    provider: str | None = None
    caller_ids: list[str] = []
    is_active: bool = True


class SipTrunkUpdate(BaseModel):
    name: NonEmpty | None = None
    market: Market | None = None
    livekit_trunk_id: str | None = None
    provider: str | None = None
    caller_ids: list[str] | None = None
    is_active: bool | None = None


class SipTrunkOut(ORM):
    id: uuid.UUID
    name: str
    market: Market
    livekit_trunk_id: str | None
    provider: str | None
    caller_ids: list[str]
    is_active: bool


# --- teams ----------------------------------------------------------------------------------


class TeamIn(BaseModel):
    name: NonEmpty
    client_id: uuid.UUID | None = None
    notify_emails: list[EmailStr] = []
    webhook_url: str | None = None
    timezone: str
    member_ids: list[uuid.UUID] = []

    _tz = field_validator("timezone")(_check_tz)


class TeamUpdate(BaseModel):
    name: NonEmpty | None = None
    client_id: uuid.UUID | None = None
    notify_emails: list[EmailStr] | None = None
    webhook_url: str | None = None
    timezone: str | None = None
    member_ids: list[uuid.UUID] | None = None

    _tz = field_validator("timezone")(_check_tz)


class TeamOut(ORM):
    id: uuid.UUID
    name: str
    client_id: uuid.UUID | None
    notify_emails: list[str]
    webhook_url: str | None
    timezone: str
    member_ids: list[uuid.UUID] = []


class AvailabilityRuleIn(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 = Monday")
    start_time: time
    end_time: time
    max_parallel: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _order(self) -> "AvailabilityRuleIn":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class AvailabilityOverrideIn(BaseModel):
    date: date
    is_closed: bool = False
    start_time: time | None = None
    end_time: time | None = None


class AvailabilityIn(BaseModel):
    rules: list[AvailabilityRuleIn]
    overrides: list[AvailabilityOverrideIn] = []


class AvailabilityRuleOut(AvailabilityRuleIn, ORM):
    id: uuid.UUID


class AvailabilityOverrideOut(AvailabilityOverrideIn, ORM):
    id: uuid.UUID


class AvailabilityOut(BaseModel):
    rules: list[AvailabilityRuleOut]
    overrides: list[AvailabilityOverrideOut]


# --- campaigns ------------------------------------------------------------------------------

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# Compliance: never before 08:00 or after 21:00 prospect-local (01 §4).
EARLIEST, LATEST = "08:00", "21:00"


def default_calling_window() -> dict[str, list[list[str]]]:
    """B2B default: Mon–Fri 09:00–17:30 prospect-local (01 §4)."""
    return {d: [["09:00", "17:30"]] for d in WEEKDAYS[:5]}


def validate_calling_window(v: dict[str, Any]) -> dict[str, list[list[str]]]:
    out: dict[str, list[list[str]]] = {}
    for day, ranges in v.items():
        if day not in WEEKDAYS:
            raise ValueError(f"unknown weekday {day!r} (use {', '.join(WEEKDAYS)})")
        if not isinstance(ranges, list):
            raise ValueError(f"{day}: expected a list of [start, end] ranges")
        clean = []
        for r in ranges:
            if not (isinstance(r, list | tuple) and len(r) == 2):
                raise ValueError(f"{day}: each range must be [start, end]")
            start, end = str(r[0]), str(r[1])
            if not (HHMM.match(start) and HHMM.match(end)):
                raise ValueError(f"{day}: times must be HH:MM")
            if start >= end:
                raise ValueError(f"{day}: {start}–{end} ends before it starts")
            if start < EARLIEST or end > LATEST:
                raise ValueError(f"{day}: calling window must stay within {EARLIEST}–{LATEST}")
            clean.append([start, end])
        clean.sort()
        for a, b in zip(clean, clean[1:], strict=False):
            if b[0] < a[1]:
                raise ValueError(f"{day}: ranges overlap")
        if clean:
            out[day] = clean
    return out


class ComplianceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ai_disclosure: Literal["on_ask", "upfront"] = "on_ask"
    ai_disclosure_text: str | None = None
    recording_notice: bool = False
    recording_notice_text: str | None = None
    dnc_scrub: bool = True


class AppointmentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: AppointmentType = AppointmentType.phone
    duration_min: int = Field(default=20, ge=5, le=480)
    team_id: uuid.UUID | None = None
    buffer_min: int = Field(default=0, ge=0, le=240)
    lead_time_hours: int = Field(default=24, ge=0, le=24 * 30)
    max_days_ahead: int = Field(default=10, ge=1, le=90)


class CampaignBase(BaseModel):
    name: NonEmpty
    client_id: uuid.UUID
    market: Market
    country_codes: list[Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$")]] = []
    default_timezone: str
    languages: list[str] = []
    sip_trunk_id: uuid.UUID | None = None
    caller_id: str | None = None
    calling_window: dict[str, Any] = Field(default_factory=default_calling_window)
    max_attempts: int = Field(default=3, ge=1, le=20)
    retry_spacing_hours: int = Field(default=4, ge=0, le=24 * 14)
    voicemail_counts_as_attempt: bool = False
    concurrency: int = Field(default=2, ge=1, le=20)
    daily_cap: int | None = Field(default=None, ge=0)
    daily_budget_usd: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=4)
    test_mode: bool = True
    test_allowlist: list[str] = []
    requeue_no_show: bool = False
    appointment_settings: AppointmentSettings = Field(default_factory=AppointmentSettings)
    compliance: ComplianceSettings = Field(default_factory=ComplianceSettings)

    _tz = field_validator("default_timezone")(_check_tz)
    _cw = field_validator("calling_window")(validate_calling_window)

    @field_validator("country_codes")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [c.upper() for c in v]


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    """PATCH: every field optional; validated the same way as create."""

    name: NonEmpty | None = None
    client_id: uuid.UUID | None = None
    market: Market | None = None
    country_codes: list[Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$")]] | None = None
    default_timezone: str | None = None
    languages: list[str] | None = None
    sip_trunk_id: uuid.UUID | None = None
    caller_id: str | None = None
    calling_window: dict[str, Any] | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    retry_spacing_hours: int | None = Field(default=None, ge=0, le=24 * 14)
    voicemail_counts_as_attempt: bool | None = None
    concurrency: int | None = Field(default=None, ge=1, le=20)
    daily_cap: int | None = Field(default=None, ge=0)
    daily_budget_usd: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=4)
    test_mode: bool | None = None
    test_allowlist: list[str] | None = None
    requeue_no_show: bool | None = None
    appointment_settings: AppointmentSettings | None = None
    compliance: ComplianceSettings | None = None

    _tz = field_validator("default_timezone")(_check_tz)

    @field_validator("calling_window")
    @classmethod
    def _cw(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if v is None else validate_calling_window(v)

    @field_validator("country_codes")
    @classmethod
    def _upper(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else [c.upper() for c in v]


class CampaignOut(ORM):
    id: uuid.UUID
    client_id: uuid.UUID
    name: str
    status: CampaignStatus
    market: Market
    country_codes: list[str]
    default_timezone: str
    languages: list[str]
    sip_trunk_id: uuid.UUID | None
    caller_id: str | None
    calling_window: dict[str, Any]
    max_attempts: int
    retry_spacing_hours: int
    voicemail_counts_as_attempt: bool
    concurrency: int
    daily_cap: int | None
    daily_budget_usd: Decimal | None
    test_mode: bool
    test_allowlist: list[str]
    requeue_no_show: bool
    appointment_settings: dict[str, Any]
    compliance: dict[str, Any]
    active_playbook_version_id: uuid.UUID | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    lead_counts: dict[str, int] = {}


class PlaybookIn(BaseModel):
    playbook: dict[str, Any]
    notes: str | None = None
    source: PlaybookSource = PlaybookSource.manual


class PlaybookOut(ORM):
    id: uuid.UUID
    campaign_id: uuid.UUID
    version: int
    playbook: dict[str, Any]
    json_schema_version: str | None
    notes: str | None
    source: PlaybookSource
    created_by: uuid.UUID | None
    is_active: bool
    created_at: datetime


class ActivateIn(BaseModel):
    override_reason: str | None = Field(
        default=None, description="Admin-only: bypass the eval gate (audit-logged)."
    )


# --- leads ----------------------------------------------------------------------------------


class LeadCreate(BaseModel):
    phone: NonEmpty
    phone_alt: str | None = None
    external_id: str | None = None
    business_name: str | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    email: str | None = None
    address_line: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    timezone: str | None = None
    website: str | None = None
    industry: str | None = None
    custom: dict[str, Any] = {}
    priority: int = 0
    notes: str | None = None

    _tz = field_validator("timezone")(_check_tz)


class LeadUpdate(BaseModel):
    phone: NonEmpty | None = None
    phone_alt: str | None = None
    business_name: str | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    email: str | None = None
    address_line: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    timezone: str | None = None
    website: str | None = None
    industry: str | None = None
    custom: dict[str, Any] | None = None
    priority: int | None = None
    notes: str | None = None

    _tz = field_validator("timezone")(_check_tz)


class LeadOut(ORM):
    id: uuid.UUID
    campaign_id: uuid.UUID
    external_id: str | None
    source: LeadSource
    business_name: str | None
    contact_name: str | None
    contact_title: str | None
    phone_e164: str
    phone_alt_e164: str | None
    email: str | None
    address_line: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country_code: str | None
    timezone: str | None
    website: str | None
    industry: str | None
    custom: dict[str, Any]
    status: LeadStatus
    attempts: int
    next_attempt_at: datetime | None
    last_attempt_at: datetime | None
    last_disposition: str | None
    priority: int
    notes: str | None
    created_at: datetime
    updated_at: datetime


class BulkAction(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=10_000)
    action: Literal["requeue", "move", "dnc", "export"]
    target_campaign_id: uuid.UUID | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _target(self) -> "BulkAction":
        if self.action == "move" and self.target_campaign_id is None:
            raise ValueError("target_campaign_id is required for move")
        return self


class BulkResult(BaseModel):
    action: str
    updated: int
    skipped: list[dict[str, Any]] = []


class ImportRowIssue(BaseModel):
    row: int  # 1-based data row number (header excluded)
    reason: Literal["invalid", "duplicate", "dnc"]
    detail: str
    value: str | None = None


class ImportReport(BaseModel):
    import_id: uuid.UUID | None
    dry_run: bool
    filename: str | None
    headers: list[str]
    column_map: dict[str, str]
    suggested_column_map: dict[str, str]
    row_count: int
    imported: int
    skipped_dupe: int
    skipped_dnc: int
    skipped_invalid: int
    issues: list[ImportRowIssue]
    preview: list[dict[str, Any]]


class LeadImportOut(ORM):
    id: uuid.UUID
    campaign_id: uuid.UUID
    filename: str | None
    row_count: int
    imported: int
    skipped_dupe: int
    skipped_dnc: int
    errors: list[Any]
    column_map: dict[str, Any]
    created_by: uuid.UUID | None
    created_at: datetime


class TimelineItem(BaseModel):
    ts: datetime
    kind: str
    title: str
    data: dict[str, Any] = {}


# --- dnc ------------------------------------------------------------------------------------


class DncIn(BaseModel):
    phone: NonEmpty
    scope: DncScope = DncScope.global_
    client_id: uuid.UUID | None = None
    reason: str | None = None
    default_region: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")

    @model_validator(mode="after")
    def _scope(self) -> "DncIn":
        if self.scope == DncScope.client and self.client_id is None:
            raise ValueError("client_id is required for client-scoped DNC")
        if self.scope == DncScope.global_:
            self.client_id = None
        return self


class DncOut(ORM):
    id: uuid.UUID
    phone_e164: str
    scope: DncScope
    client_id: uuid.UUID | None
    reason: str | None
    source: str | None
    created_by: uuid.UUID | None
    created_at: datetime


class DncCheckIn(BaseModel):
    phones: list[str] = Field(max_length=10_000)
    client_id: uuid.UUID | None = None
    default_region: str | None = None


class DncCheckOut(BaseModel):
    results: dict[str, bool]
    invalid: list[str]
