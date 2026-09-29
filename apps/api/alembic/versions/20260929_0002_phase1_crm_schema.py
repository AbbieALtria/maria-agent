"""phase 1: CRM schema — all tables from docs/outbound/03-CRM-DATA-MODEL.md §1

Enums are created up front (several tables share `market`); the two circular foreign keys
(campaigns.active_playbook_version_id, call_attempts.appointment_id) are added after all tables.

Revision ID: 0002_phase1
Revises: 0001_phase0_5
Create Date: 2026-09-29 03:41:40.312090
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002_phase1"
down_revision: str | None = "0001_phase0_5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ENUMS: dict[str, tuple[str, ...]] = {
    "market": (
        "US",
        "CA",
        "PH",
        "OTHER",
    ),
    "user_role": (
        "admin",
        "manager",
        "rep",
        "qa",
    ),
    "campaign_status": (
        "draft",
        "testing",
        "active",
        "paused",
        "completed",
    ),
    "dnc_scope": (
        "global",
        "client",
    ),
    "lead_source": (
        "csv",
        "openleads",
        "manual",
        "vicidial",
        "api",
    ),
    "lead_status": (
        "new",
        "queued",
        "calling",
        "contacted",
        "callback",
        "appointment_set",
        "not_interested",
        "wrong_number",
        "dnc",
        "exhausted",
        "invalid",
        "paused",
    ),
    "objection_source": (
        "recording",
        "qa",
        "manual",
    ),
    "playbook_source": (
        "manual",
        "learning",
        "import",
    ),
    "recording_status": (
        "uploaded",
        "transcribed",
        "analyzed",
        "failed",
    ),
    "attempt_status": (
        "dialing",
        "ringing",
        "in_call",
        "completed",
        "failed",
        "failed_stale",
    ),
    "amd_result": (
        "human",
        "machine_vm",
        "machine_ivr",
        "machine_unavailable",
        "uncertain",
    ),
    "call_outcome": (
        "conversation",
        "voicemail",
        "ivr",
        "no_answer",
        "busy",
        "failed",
        "invalid_number",
        "no_human",
        "hung_up_early",
    ),
    "appointment_type": (
        "phone",
        "video",
        "onsite",
    ),
    "appointment_status": (
        "scheduled",
        "confirmed",
        "rescheduled",
        "cancelled",
        "completed",
        "no_show",
    ),
    "appointment_outcome": (
        "sold",
        "follow_up",
        "lost",
        "pending",
    ),
    "consent_type": (
        "opt_out",
        "recording_ack",
        "ai_disclosed",
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "clients",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("contact_email", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
    )
    op.create_table(
        "sip_trunks",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("market", postgresql.ENUM(name="market", create_type=False), nullable=False),
        sa.Column("livekit_trunk_id", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("caller_ids", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sip_trunks")),
    )
    op.create_table(
        "api_keys",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_api_keys_client_id_clients"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
    )
    op.create_table(
        "teams",
        sa.Column("client_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "notify_emails", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_teams_client_id_clients"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_teams")),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("role", postgresql.ENUM(name="user_role", create_type=False), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_users_client_id_clients"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "audit_log",
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_log_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity", "entity_id"], unique=False)
    op.create_table(
        "availability_overrides",
        sa.Column("team_id", sa.UUID(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_availability_overrides_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_availability_overrides")),
    )
    op.create_table(
        "availability_rules",
        sa.Column("team_id", sa.UUID(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("max_parallel", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("end_time > start_time", name=op.f("ck_availability_rules_time_order")),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_availability_rules_weekday_range")
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_availability_rules_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_availability_rules")),
    )
    op.create_table(
        "campaigns",
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="campaign_status", create_type=False),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("market", postgresql.ENUM(name="market", create_type=False), nullable=False),
        sa.Column(
            "country_codes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("default_timezone", sa.Text(), nullable=False),
        sa.Column("languages", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("sip_trunk_id", sa.UUID(), nullable=True),
        sa.Column("caller_id", sa.Text(), nullable=True),
        sa.Column(
            "calling_window",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("retry_spacing_hours", sa.Integer(), server_default="4", nullable=False),
        sa.Column(
            "voicemail_counts_as_attempt",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("concurrency", sa.Integer(), server_default="2", nullable=False),
        sa.Column("daily_cap", sa.Integer(), nullable=True),
        sa.Column("daily_budget_usd", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("test_mode", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "test_allowlist", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("requeue_no_show", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "appointment_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "compliance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("active_playbook_version_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "concurrency >= 1 AND concurrency <= 20", name=op.f("ck_campaigns_concurrency_range")
        ),
        sa.CheckConstraint("max_attempts >= 1", name=op.f("ck_campaigns_max_attempts_positive")),
        sa.CheckConstraint(
            "retry_spacing_hours >= 0", name=op.f("ck_campaigns_retry_spacing_nonneg")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_campaigns_client_id_clients"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_campaigns_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sip_trunk_id"],
            ["sip_trunks.id"],
            name=op.f("fk_campaigns_sip_trunk_id_sip_trunks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
    )
    op.create_table(
        "dnc_entries",
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("scope", postgresql.ENUM(name="dnc_scope", create_type=False), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND client_id IS NULL) OR (scope = 'client' AND client_id IS NOT NULL)",
            name=op.f("ck_dnc_entries_scope_client"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_dnc_entries_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_dnc_entries_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dnc_entries")),
        sa.UniqueConstraint(
            "phone_e164",
            "scope",
            "client_id",
            name="uq_dnc_entries_phone_scope_client",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_dnc_entries_phone_e164", "dnc_entries", ["phone_e164"], unique=False)
    op.create_table(
        "team_members",
        sa.Column("team_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_team_members_team_id_teams"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_team_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_members")),
        sa.UniqueConstraint("team_id", "user_id", name=op.f("uq_team_members_team_id")),
    )
    op.create_table(
        "analysis_runs",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column(
            "recording_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False
        ),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("playbook_draft", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("eval_scenarios", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_analysis_runs_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_analysis_runs_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_runs")),
    )
    op.create_table(
        "eval_scenarios",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column(
            "persona", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("expected_outcome", sa.Text(), nullable=True),
        sa.Column("script_hints", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_eval_scenarios_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_scenarios")),
    )
    op.create_table(
        "lead_imports",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("imported", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_dupe", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_dnc", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "errors", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "column_map",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_lead_imports_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_lead_imports_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_imports")),
    )
    op.create_table(
        "leads",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column(
            "source",
            postgresql.ENUM(name="lead_source", create_type=False),
            server_default="manual",
            nullable=False,
        ),
        sa.Column("business_name", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.Text(), nullable=True),
        sa.Column("contact_title", sa.Text(), nullable=True),
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("phone_alt_e164", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("address_line", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.Text(), nullable=True),
        sa.Column("country_code", sa.Text(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column(
            "custom", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="lead_status", create_type=False),
            server_default="new",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_disposition", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_leads_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
        sa.UniqueConstraint("campaign_id", "phone_e164", name=op.f("uq_leads_campaign_id")),
    )
    op.create_index(
        "ix_leads_campaign_status_next_attempt",
        "leads",
        ["campaign_id", "status", "next_attempt_at"],
        unique=False,
    )
    op.create_table(
        "objection_library",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("objection", sa.Text(), nullable=False),
        sa.Column("rebuttal", sa.Text(), nullable=True),
        sa.Column(
            "source", postgresql.ENUM(name="objection_source", create_type=False), nullable=False
        ),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("effectiveness_score", sa.Numeric(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_objection_library_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_objection_library")),
    )
    op.create_index(
        "ix_objection_library_embedding",
        "objection_library",
        ["embedding"],
        unique=False,
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "playbook_versions",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("playbook", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("json_schema_version", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "source",
            postgresql.ENUM(name="playbook_source", create_type=False),
            server_default="manual",
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_playbook_versions_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_playbook_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playbook_versions")),
        sa.UniqueConstraint(
            "campaign_id", "version", name=op.f("uq_playbook_versions_campaign_id")
        ),
    )
    op.create_table(
        "training_recordings",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("storage_url", sa.Text(), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("outcome_label", sa.Text(), nullable=True),
        sa.Column("agent_name", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="recording_status", create_type=False),
            server_default="uploaded",
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_training_recordings_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_training_recordings_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_recordings")),
    )
    op.create_table(
        "call_attempts",
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("playbook_version_id", sa.UUID(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="attempt_status", create_type=False),
            server_default="dialing",
            nullable=False,
        ),
        sa.Column("sip_status", sa.Text(), nullable=True),
        sa.Column("sip_error", sa.Text(), nullable=True),
        sa.Column(
            "amd_result", postgresql.ENUM(name="amd_result", create_type=False), nullable=True
        ),
        sa.Column(
            "outcome", postgresql.ENUM(name="call_outcome", create_type=False), nullable=True
        ),
        sa.Column("disposition", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("human_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("talk_sec", sa.Integer(), nullable=True),
        sa.Column("livekit_room", sa.Text(), nullable=True),
        sa.Column("recording_url", sa.Text(), nullable=True),
        sa.Column("recording_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "transcript",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.Text(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("stage_reached", sa.Text(), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("appointment_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_call_attempts_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_call_attempts_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["playbook_version_id"],
            ["playbook_versions.id"],
            name=op.f("fk_call_attempts_playbook_version_id_playbook_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_attempts")),
    )
    op.create_index(
        "ix_call_attempts_campaign_started",
        "call_attempts",
        ["campaign_id", "started_at"],
        unique=False,
    )
    op.create_index("ix_call_attempts_lead_id", "call_attempts", ["lead_id"], unique=False)
    op.create_table(
        "eval_runs",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("playbook_version_id", sa.UUID(), nullable=False),
        sa.Column("scenario_id", sa.UUID(), nullable=True),
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("grader_notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_eval_runs_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["playbook_version_id"],
            ["playbook_versions.id"],
            name=op.f("fk_eval_runs_playbook_version_id_playbook_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["eval_scenarios.id"],
            name=op.f("fk_eval_runs_scenario_id_eval_scenarios"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_runs")),
    )
    op.create_index(
        "ix_eval_runs_playbook_version", "eval_runs", ["playbook_version_id"], unique=False
    )
    op.create_table(
        "appointments",
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("call_attempt_id", sa.UUID(), nullable=True),
        sa.Column("team_id", sa.UUID(), nullable=True),
        sa.Column("assigned_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "type", postgresql.ENUM(name="appointment_type", create_type=False), nullable=False
        ),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prospect_timezone", sa.Text(), nullable=True),
        sa.Column("location_address", sa.Text(), nullable=True),
        sa.Column("meeting_link", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(name="appointment_status", create_type=False),
            server_default="scheduled",
            nullable=False,
        ),
        sa.Column(
            "outcome",
            postgresql.ENUM(name="appointment_outcome", create_type=False),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("confirmation_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_24h_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_2h_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("end_at > start_at", name=op.f("ck_appointments_time_order")),
        sa.ForeignKeyConstraint(
            ["assigned_user_id"],
            ["users.id"],
            name=op.f("fk_appointments_assigned_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["call_attempt_id"],
            ["call_attempts.id"],
            name=op.f("fk_appointments_call_attempt_id_call_attempts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_appointments_campaign_id_campaigns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_appointments_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name=op.f("fk_appointments_team_id_teams"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointments")),
    )
    op.create_index("ix_appointments_lead_id", "appointments", ["lead_id"], unique=False)
    op.create_index(
        "ix_appointments_team_start", "appointments", ["team_id", "start_at"], unique=False
    )
    op.create_table(
        "call_events",
        sa.Column("call_attempt_id", sa.UUID(), nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["call_attempt_id"],
            ["call_attempts.id"],
            name=op.f("fk_call_events_call_attempt_id_call_attempts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_events")),
    )
    op.create_index(
        "ix_call_events_attempt_ts", "call_events", ["call_attempt_id", "ts"], unique=False
    )
    op.create_table(
        "call_reviews",
        sa.Column("call_attempt_id", sa.UUID(), nullable=False),
        sa.Column("reviewer_id", sa.UUID(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("corrections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("score BETWEEN 1 AND 5", name=op.f("ck_call_reviews_score_range")),
        sa.ForeignKeyConstraint(
            ["call_attempt_id"],
            ["call_attempts.id"],
            name=op.f("fk_call_reviews_call_attempt_id_call_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name=op.f("fk_call_reviews_reviewer_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_reviews")),
    )
    op.create_table(
        "consent_events",
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("call_attempt_id", sa.UUID(), nullable=True),
        sa.Column("type", postgresql.ENUM(name="consent_type", create_type=False), nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["call_attempt_id"],
            ["call_attempts.id"],
            name=op.f("fk_consent_events_call_attempt_id_call_attempts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_consent_events_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_events")),
    )
    op.create_table(
        "appointment_events",
        sa.Column("appointment_id", sa.UUID(), nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_appointment_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name=op.f("fk_appointment_events_appointment_id_appointments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_events")),
    )
    op.create_foreign_key(
        "fk_campaigns_active_playbook_version_id_playbook_versions",
        "campaigns",
        "playbook_versions",
        ["active_playbook_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_call_attempts_appointment_id_appointments",
        "call_attempts",
        "appointments",
        ["appointment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_call_attempts_appointment_id_appointments", "call_attempts", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_campaigns_active_playbook_version_id_playbook_versions", "campaigns", type_="foreignkey"
    )
    op.drop_table("appointment_events")
    op.drop_table("consent_events")
    op.drop_table("call_reviews")
    op.drop_index("ix_call_events_attempt_ts", table_name="call_events")
    op.drop_table("call_events")
    op.drop_index("ix_appointments_team_start", table_name="appointments")
    op.drop_index("ix_appointments_lead_id", table_name="appointments")
    op.drop_table("appointments")
    op.drop_index("ix_eval_runs_playbook_version", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_call_attempts_lead_id", table_name="call_attempts")
    op.drop_index("ix_call_attempts_campaign_started", table_name="call_attempts")
    op.drop_table("call_attempts")
    op.drop_table("training_recordings")
    op.drop_table("playbook_versions")
    op.drop_index(
        "ix_objection_library_embedding",
        table_name="objection_library",
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("objection_library")
    op.drop_index("ix_leads_campaign_status_next_attempt", table_name="leads")
    op.drop_table("leads")
    op.drop_table("lead_imports")
    op.drop_table("eval_scenarios")
    op.drop_table("analysis_runs")
    op.drop_table("team_members")
    op.drop_index("ix_dnc_entries_phone_e164", table_name="dnc_entries")
    op.drop_table("dnc_entries")
    op.drop_table("campaigns")
    op.drop_table("availability_rules")
    op.drop_table("availability_overrides")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("users")
    op.drop_table("teams")
    op.drop_table("api_keys")
    op.drop_table("sip_trunks")
    op.drop_table("clients")
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
