"""Campaign playbook models (docs/outbound/04-CAMPAIGN-PLAYBOOK-SPEC.md)."""

from pathlib import Path

from playbook_schema.models import (
    REQUIRED_DISPOSITIONS,
    SCHEMA_VERSION,
    STAGES,
    Playbook,
    export_json_schema,
    validation_errors,
)
from playbook_schema.prompt import build_system_prompt

__version__ = "0.2.0"

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"

__all__ = [
    "EXAMPLES_DIR",
    "REQUIRED_DISPOSITIONS",
    "SCHEMA_VERSION",
    "STAGES",
    "Playbook",
    "build_system_prompt",
    "export_json_schema",
    "validation_errors",
]
