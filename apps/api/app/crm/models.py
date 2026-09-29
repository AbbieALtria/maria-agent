"""CRM tables (docs/outbound/03-CRM-DATA-MODEL.md §1). Learning tables live in app/learning."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.crm.enums import (
    AmdResult,
    AppointmentOutcome,
    AppointmentStatus,
    AppointmentType,
    AttemptStatus,
    CallOutcome,
    CampaignStatus,
    ConsentType,
    DncScope,
    LeadSource,
    LeadStatus,
    Market,
    PlaybookSource,
    UserRole,
    pg_enum,
)
from app.db import Base
from app.models_base import IdTimestampMixin

Money = Numeric(12, 4)
TextArray = ARRAY(Text)


def uuid_col(target: str, ondelete: str = "SET NULL", nullable: bool = True) -> Any:
    """UUID foreign-key column."""
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable
    )


# --- Tenancy / people -------------------------------------------------------------------------


class Client(IdTimestampMixin, Base):
    __tablename__ = "clients"
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_email: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)


class User(IdTimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"), nullable=False)
    client_id: Mapped[uuid.UUID | None] = uuid_col("clients.id")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)


class ApiKey(IdTimestampMixin, Base):
    __tablename__ = "api_keys"
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(TextArray, server_default="{}", nullable=False)
    client_id: Mapped[uuid.UUID | None] = uuid_col("clients.id")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Telephony config -------------------------------------------------------------------------


class SipTrunk(IdTimestampMixin, Base):
    __tablename__ = "sip_trunks"
    name: Mapped[str] = mapped_column(Text, nullable=False)
    market: Mapped[Market] = mapped_column(pg_enum(Market, "market"), nullable=False)
    livekit_trunk_id: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    caller_ids: Mapped[list[str]] = mapped_column(TextArray, server_default="{}", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)


# --- Campaigns --------------------------------------------------------------------------------


class Campaign(IdTimestampMixin, Base):
    __tablename__ = "campaigns"
    client_id: Mapped[uuid.UUID] = uuid_col("clients.id", "RESTRICT", nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[CampaignStatus] = mapped_column(
        pg_enum(CampaignStatus, "campaign_status"), server_default="draft", nullable=False
    )
    market: Mapped[Market] = mapped_column(pg_enum(Market, "market"), nullable=False)
    country_codes: Mapped[list[str]] = mapped_column(TextArray, server_default="{}", nullable=False)
    default_timezone: Mapped[str] = mapped_column(Text, nullable=False)
    languages: Mapped[list[str]] = mapped_column(TextArray, server_default="{}", nullable=False)
    sip_trunk_id: Mapped[uuid.UUID | None] = uuid_col("sip_trunks.id")
    caller_id: Mapped[str | None] = mapped_column(Text)
    calling_window: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3", nullable=False)
    retry_spacing_hours: Mapped[int] = mapped_column(Integer, server_default="4", nullable=False)
    voicemail_counts_as_attempt: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    concurrency: Mapped[int] = mapped_column(Integer, server_default="2", nullable=False)
    daily_cap: Mapped[int | None] = mapped_column(Integer)
    daily_budget_usd: Mapped[Decimal | None] = mapped_column(Money)
    test_mode: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    test_allowlist: Mapped[list[str]] = mapped_column(
        TextArray, server_default="{}", nullable=False
    )
    requeue_no_show: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    appointment_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", nullable=False
    )
    compliance: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    active_playbook_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "playbook_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_campaigns_active_playbook_version_id_playbook_versions",
        ),
    )
    created_by: Mapped[uuid.UUID | None] = uuid_col("users.id")

    __table_args__ = (
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        CheckConstraint("concurrency >= 1 AND concurrency <= 20", name="concurrency_range"),
        CheckConstraint("retry_spacing_hours >= 0", name="retry_spacing_nonneg"),
    )


class PlaybookVersion(IdTimestampMixin, Base):
    __tablename__ = "playbook_versions"
    campaign_id: Mapped[uuid.UUID] = uuid_col("campaigns.id", "CASCADE", nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    playbook: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    json_schema_version: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[PlaybookSource] = mapped_column(
        pg_enum(PlaybookSource, "playbook_source"), server_default="manual", nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = uuid_col("users.id")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)

    __table_args__ = (UniqueConstraint("campaign_id", "version"),)


class Team(IdTimestampMixin, Base):
    __tablename__ = "teams"
    client_id: Mapped[uuid.UUID | None] = uuid_col("clients.id")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    notify_emails: Mapped[list[str]] = mapped_column(TextArray, server_default="{}", nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)


class TeamMember(IdTimestampMixin, Base):
    __tablename__ = "team_members"
    team_id: Mapped[uuid.UUID] = uuid_col("teams.id", "CASCADE", nullable=False)
    user_id: Mapped[uuid.UUID] = uuid_col("users.id", "CASCADE", nullable=False)

    __table_args__ = (UniqueConstraint("team_id", "user_id"),)


class AvailabilityRule(IdTimestampMixin, Base):
    __tablename__ = "availability_rules"
    team_id: Mapped[uuid.UUID] = uuid_col("teams.id", "CASCADE", nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 = Monday … 6 = Sunday
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    max_parallel: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="time_order"),
    )


class AvailabilityOverride(IdTimestampMixin, Base):
    __tablename__ = "availability_overrides"
    team_id: Mapped[uuid.UUID] = uuid_col("teams.id", "CASCADE", nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)


# --- Leads ------------------------------------------------------------------------------------


class Lead(IdTimestampMixin, Base):
    __tablename__ = "leads"
    campaign_id: Mapped[uuid.UUID] = uuid_col("campaigns.id", "CASCADE", nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    source: Mapped[LeadSource] = mapped_column(
        pg_enum(LeadSource, "lead_source"), server_default="manual", nullable=False
    )
    business_name: Mapped[str | None] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_title: Mapped[str | None] = mapped_column(Text)
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    phone_alt_e164: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    address_line: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    custom: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    status: Mapped[LeadStatus] = mapped_column(
        pg_enum(LeadStatus, "lead_status"), server_default="new", nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_disposition: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("campaign_id", "phone_e164"),
        Index("ix_leads_campaign_status_next_attempt", "campaign_id", "status", "next_attempt_at"),
    )


class LeadImport(IdTimestampMixin, Base):
    __tablename__ = "lead_imports"
    campaign_id: Mapped[uuid.UUID] = uuid_col("campaigns.id", "CASCADE", nullable=False)
    filename: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    imported: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    skipped_dupe: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    skipped_dnc: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    errors: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]", nullable=False)
    column_map: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    created_by: Mapped[uuid.UUID | None] = uuid_col("users.id")


# --- Calls ------------------------------------------------------------------------------------


class CallAttempt(IdTimestampMixin, Base):
    __tablename__ = "call_attempts"
    lead_id: Mapped[uuid.UUID] = uuid_col("leads.id", "CASCADE", nullable=False)
    campaign_id: Mapped[uuid.UUID] = uuid_col("campaigns.id", "CASCADE", nullable=False)
    playbook_version_id: Mapped[uuid.UUID | None] = uuid_col("playbook_versions.id")
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AttemptStatus] = mapped_column(
        pg_enum(AttemptStatus, "attempt_status"), server_default="dialing", nullable=False
    )
    sip_status: Mapped[str | None] = mapped_column(Text)
    sip_error: Mapped[str | None] = mapped_column(Text)
    amd_result: Mapped[AmdResult | None] = mapped_column(pg_enum(AmdResult, "amd_result"))
    outcome: Mapped[CallOutcome | None] = mapped_column(pg_enum(CallOutcome, "call_outcome"))
    disposition: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    human_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    talk_sec: Mapped[int | None] = mapped_column(Integer)
    livekit_room: Mapped[str | None] = mapped_column(Text)
    recording_url: Mapped[str | None] = mapped_column(Text)
    recording_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transcript: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]", nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    review_reason: Mapped[str | None] = mapped_column(Text)
    stage_reached: Mapped[str | None] = mapped_column(Text)
    end_reason: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cost_usd: Mapped[Decimal | None] = mapped_column(Money)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "appointments.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_call_attempts_appointment_id_appointments",
        ),
    )

    __table_args__ = (
        Index("ix_call_attempts_campaign_started", "campaign_id", "started_at"),
        Index("ix_call_attempts_lead_id", "lead_id"),
    )


class CallEvent(IdTimestampMixin, Base):
    __tablename__ = "call_events"
    call_attempt_id: Mapped[uuid.UUID] = uuid_col("call_attempts.id", "CASCADE", nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)

    __table_args__ = (Index("ix_call_events_attempt_ts", "call_attempt_id", "ts"),)


class CallReview(IdTimestampMixin, Base):
    __tablename__ = "call_reviews"
    call_attempt_id: Mapped[uuid.UUID] = uuid_col("call_attempts.id", "CASCADE", nullable=False)
    reviewer_id: Mapped[uuid.UUID | None] = uuid_col("users.id")
    score: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list[str]] = mapped_column(TextArray, server_default="{}", nullable=False)
    comments: Mapped[str | None] = mapped_column(Text)
    corrections: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (CheckConstraint("score BETWEEN 1 AND 5", name="score_range"),)


# --- Appointments -----------------------------------------------------------------------------


class Appointment(IdTimestampMixin, Base):
    __tablename__ = "appointments"
    lead_id: Mapped[uuid.UUID] = uuid_col("leads.id", "CASCADE", nullable=False)
    campaign_id: Mapped[uuid.UUID] = uuid_col("campaigns.id", "CASCADE", nullable=False)
    call_attempt_id: Mapped[uuid.UUID | None] = uuid_col("call_attempts.id")
    team_id: Mapped[uuid.UUID | None] = uuid_col("teams.id")
    assigned_user_id: Mapped[uuid.UUID | None] = uuid_col("users.id")
    type: Mapped[AppointmentType] = mapped_column(
        pg_enum(AppointmentType, "appointment_type"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prospect_timezone: Mapped[str | None] = mapped_column(Text)
    location_address: Mapped[str | None] = mapped_column(Text)
    meeting_link: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AppointmentStatus] = mapped_column(
        pg_enum(AppointmentStatus, "appointment_status"),
        server_default="scheduled",
        nullable=False,
    )
    outcome: Mapped[AppointmentOutcome] = mapped_column(
        pg_enum(AppointmentOutcome, "appointment_outcome"),
        server_default="pending",
        nullable=False,
    )
    value: Mapped[Decimal | None] = mapped_column(Money)
    notes: Mapped[str | None] = mapped_column(Text)
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_24h_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_2h_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_appointments_team_start", "team_id", "start_at"),
        Index("ix_appointments_lead_id", "lead_id"),
        CheckConstraint("end_at > start_at", name="time_order"),
    )


class AppointmentEvent(IdTimestampMixin, Base):
    __tablename__ = "appointment_events"
    appointment_id: Mapped[uuid.UUID] = uuid_col("appointments.id", "CASCADE", nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = uuid_col("users.id")


# --- Compliance -------------------------------------------------------------------------------


class DncEntry(IdTimestampMixin, Base):
    __tablename__ = "dnc_entries"
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[DncScope] = mapped_column(pg_enum(DncScope, "dnc_scope"), nullable=False)
    client_id: Mapped[uuid.UUID | None] = uuid_col("clients.id", "CASCADE")
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = uuid_col("users.id")

    __table_args__ = (
        # NULLS NOT DISTINCT so a global entry (client_id NULL) can't be duplicated (PG 15+).
        UniqueConstraint(
            "phone_e164",
            "scope",
            "client_id",
            name="uq_dnc_entries_phone_scope_client",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_dnc_entries_phone_e164", "phone_e164"),
        CheckConstraint(
            "(scope = 'global' AND client_id IS NULL)"
            " OR (scope = 'client' AND client_id IS NOT NULL)",
            name="scope_client",
        ),
    )


class ConsentEvent(IdTimestampMixin, Base):
    __tablename__ = "consent_events"
    lead_id: Mapped[uuid.UUID] = uuid_col("leads.id", "CASCADE", nullable=False)
    call_attempt_id: Mapped[uuid.UUID | None] = uuid_col("call_attempts.id")
    type: Mapped[ConsentType] = mapped_column(pg_enum(ConsentType, "consent_type"), nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(IdTimestampMixin, Base):
    __tablename__ = "audit_log"
    actor_user_id: Mapped[uuid.UUID | None] = uuid_col("users.id")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_audit_log_entity", "entity", "entity_id"),)
