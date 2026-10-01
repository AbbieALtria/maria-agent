import copy
import json

import pytest
from pydantic import ValidationError

from playbook_schema import EXAMPLES_DIR, Playbook, validation_errors
from playbook_schema.__main__ import SCHEMA_PATH, render_schema


@pytest.fixture
def example() -> dict:
    return json.loads((EXAMPLES_DIR / "yp_seo_us.json").read_text(encoding="utf-8"))


def _errors(data: dict) -> str:
    return " | ".join(validation_errors(data))


def test_example_is_valid(example) -> None:
    pb = Playbook.model_validate(example)
    assert pb.persona.agent_name == "Maria"
    assert pb.models.live and pb.models.amd
    assert pb.runtime.greeting_delay_ms == 600
    assert validation_errors(example) == []


def test_runtime_is_optional(example) -> None:
    del example["runtime"]
    assert Playbook.model_validate(example).runtime.allow_interruptions is True


def test_unknown_placeholder(example) -> None:
    example["flow"]["wrap"] = "Bye {nickname}!"
    assert "flow.wrap: unknown placeholder {nickname}" in _errors(example)


def test_lead_context_fields_are_valid_placeholders(example) -> None:
    example["flow"]["wrap"] = "Bye from {industry} land, rated {custom.rating}!"
    assert validation_errors(example) == []


def test_bad_regex(example) -> None:
    example["objections"][0]["trigger"] = "not (interested"
    assert "objections[0].trigger: invalid regex" in _errors(example)


def test_opener_rules(example) -> None:
    example["flow"]["opener"] = []
    assert "flow.opener" in _errors(example)
    example["flow"]["opener"] = ["word " * 61]
    assert "more than 60 words" in _errors(example)


def test_required_dispositions(example) -> None:
    del example["dispositions"]["dnc"]
    del example["dispositions"]["callback"]
    assert "dispositions: missing dnc, callback" in _errors(example)


def test_onsite_requires_address(example) -> None:
    example["goal"]["appointment"]["type"] = "onsite"
    assert "requires require_address" in _errors(example)
    example["goal"]["appointment"]["require_address"] = True
    assert validation_errors(example) == []


def test_disclosure_text_required(example) -> None:
    example["compliance"]["ai_disclosure_text"] = "  "
    assert "compliance.ai_disclosure_text" in _errors(example)


def test_unknown_keys_rejected(example) -> None:
    bad = copy.deepcopy(example)
    bad["persona"]["volume"] = 11
    with pytest.raises(ValidationError):
        Playbook.model_validate(bad)


def test_all_rule_errors_reported_together(example) -> None:
    example["flow"]["wrap"] = "{nope}"
    example["objections"][0]["trigger"] = "("
    errs = validation_errors(example)
    assert len([e for e in errs if "nope" in e or "regex" in e]) == 2


def test_json_schema_file_is_current() -> None:
    assert SCHEMA_PATH.read_text(encoding="utf-8") == render_schema(), (
        "run `uv run python -m playbook_schema` to regenerate playbook.schema.json"
    )
