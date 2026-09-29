"""Learning-pipeline tables (03 §1 "Learning"). Created in Phase 1, used from Phase 5."""

import uuid
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.crm.enums import ObjectionSource, RecordingStatus, pg_enum
from app.crm.models import uuid_col
from app.db import Base
from app.models_base import IdTimestampMixin

EMBEDDING_DIM = 1024


class TrainingRecording(IdTimestampMixin, Base):
    __tablename__ = "training_recordings"
    campaign_id: Mapped[uuid.UUID] = uuid_col("campaigns.id", "CASCADE", nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_url: Mapped[str | None] = mapped_column(Text)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    outcome_label: Mapped[str | None] = mapped_column(Text)
    agent_name: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = uuid_col("users.id")
    transcript: Mapped[list[Any] | None] = mapped_column(JSONB)
    status: Mapped[RecordingStatus] = mapped_column(
        pg_enum(RecordingStatus, "recording_status"), server_default="uploaded", nullable=False
    )


class AnalysisRun(IdTimestampMixin, Base):
    __tablename__ = "analysis_runs"
    campaign_id: Mapped[uuid.UUID] = uuid_col("campaigns.id", "CASCADE", nullable=False)
    recording_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}", nullable=False
    )
    model: Mapped[str | None] = mapped_column(Text)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    playbook_draft: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    eval_scenarios: Mapped[list[Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default="pending", nullable=False)
    created_by: Mapped[uuid.UUID | None] = uuid_col("users.id")


class ObjectionLibrary(IdTimestampMixin, Base):
    __tablename__ = "objection_library"
    campaign_id: Mapped[uuid.UUID] = uuid_col("campaigns.id", "CASCADE", nullable=False)
    objection: Mapped[str] = mapped_column(Text, nullable=False)
    rebuttal: Mapped[str | None] = mapped_column(Text)
    source: Mapped[ObjectionSource] = mapped_column(
        pg_enum(ObjectionSource, "objection_source"), nullable=False
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    effectiveness_score: Mapped[Decimal | None] = mapped_column(Numeric)

    __table_args__ = (
        Index(
            "ix_objection_library_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class EvalScenario(IdTimestampMixin, Base):
    __tablename__ = "eval_scenarios"
    campaign_id: Mapped[uuid.UUID] = uuid_col("campaigns.id", "CASCADE", nullable=False)
    persona: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}", nullable=False)
    expected_outcome: Mapped[str | None] = mapped_column(Text)
    script_hints: Mapped[str | None] = mapped_column(Text)


class EvalRun(IdTimestampMixin, Base):
    __tablename__ = "eval_runs"
    campaign_id: Mapped[uuid.UUID] = uuid_col("campaigns.id", "CASCADE", nullable=False)
    playbook_version_id: Mapped[uuid.UUID] = uuid_col(
        "playbook_versions.id", "CASCADE", nullable=False
    )
    scenario_id: Mapped[uuid.UUID | None] = uuid_col("eval_scenarios.id")
    transcript: Mapped[list[Any] | None] = mapped_column(JSONB)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    grader_notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_eval_runs_playbook_version", "playbook_version_id"),)
