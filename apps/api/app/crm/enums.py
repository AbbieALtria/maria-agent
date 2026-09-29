"""Postgres enums for the CRM schema (docs/outbound/03-CRM-DATA-MODEL.md §1)."""

from enum import StrEnum

import sqlalchemy as sa


class UserRole(StrEnum):
    admin = "admin"
    manager = "manager"
    rep = "rep"
    qa = "qa"


class Market(StrEnum):
    US = "US"
    CA = "CA"
    PH = "PH"
    OTHER = "OTHER"


class CampaignStatus(StrEnum):
    draft = "draft"
    testing = "testing"
    active = "active"
    paused = "paused"
    completed = "completed"


class PlaybookSource(StrEnum):
    manual = "manual"
    learning = "learning"
    import_ = "import"


class LeadSource(StrEnum):
    csv = "csv"
    openleads = "openleads"
    manual = "manual"
    vicidial = "vicidial"
    api = "api"


class LeadStatus(StrEnum):
    new = "new"
    queued = "queued"
    calling = "calling"
    contacted = "contacted"
    callback = "callback"
    appointment_set = "appointment_set"
    not_interested = "not_interested"
    wrong_number = "wrong_number"
    dnc = "dnc"
    exhausted = "exhausted"
    invalid = "invalid"
    paused = "paused"


class AttemptStatus(StrEnum):
    dialing = "dialing"
    ringing = "ringing"
    in_call = "in_call"
    completed = "completed"
    failed = "failed"
    failed_stale = "failed_stale"


class AmdResult(StrEnum):
    human = "human"
    machine_vm = "machine_vm"
    machine_ivr = "machine_ivr"
    machine_unavailable = "machine_unavailable"
    uncertain = "uncertain"


class CallOutcome(StrEnum):
    conversation = "conversation"
    voicemail = "voicemail"
    ivr = "ivr"
    no_answer = "no_answer"
    busy = "busy"
    failed = "failed"
    invalid_number = "invalid_number"
    no_human = "no_human"
    hung_up_early = "hung_up_early"


class AppointmentType(StrEnum):
    phone = "phone"
    video = "video"
    onsite = "onsite"


class AppointmentStatus(StrEnum):
    scheduled = "scheduled"
    confirmed = "confirmed"
    rescheduled = "rescheduled"
    cancelled = "cancelled"
    completed = "completed"
    no_show = "no_show"


class AppointmentOutcome(StrEnum):
    sold = "sold"
    follow_up = "follow_up"
    lost = "lost"
    pending = "pending"


class DncScope(StrEnum):
    global_ = "global"
    client = "client"


class ConsentType(StrEnum):
    opt_out = "opt_out"
    recording_ack = "recording_ack"
    ai_disclosed = "ai_disclosed"


class RecordingStatus(StrEnum):
    uploaded = "uploaded"
    transcribed = "transcribed"
    analyzed = "analyzed"
    failed = "failed"


class ObjectionSource(StrEnum):
    recording = "recording"
    qa = "qa"
    manual = "manual"


def pg_enum(enum_cls: type[StrEnum], name: str) -> sa.Enum:
    """Postgres enum storing the member *values* (so `global_` is stored as 'global')."""
    return sa.Enum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
