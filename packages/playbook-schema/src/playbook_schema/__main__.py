"""`python -m playbook_schema` → regenerate packages/playbook-schema/playbook.schema.json."""

import json
from pathlib import Path

from playbook_schema.models import export_json_schema

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "playbook.schema.json"


def render_schema() -> str:
    return json.dumps(export_json_schema(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    SCHEMA_PATH.write_text(render_schema(), encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
