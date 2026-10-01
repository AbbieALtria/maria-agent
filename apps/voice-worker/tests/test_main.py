import logging

import pytest

import main


def test_parse_metadata() -> None:
    meta = main.parse_metadata('{"attempt_id": "a1", "phone": "+12125550100", "test": true}')
    assert meta["attempt_id"] == "a1" and meta["test"] is True
    with pytest.raises(ValueError):
        main.parse_metadata("{}")
    with pytest.raises(ValueError):
        main.parse_metadata(None)


def test_call_log_adds_ids(caplog) -> None:
    log = main.CallLog(
        logging.getLogger("maria.worker.test"), {"attempt_id": "a1", "campaign_id": "c1"}
    )
    with caplog.at_level(logging.INFO, logger="maria.worker.test"):
        log.info("hello", extra={"x": 1})
    rec = caplog.records[-1]
    assert (rec.attempt_id, rec.campaign_id, rec.x) == ("a1", "c1", 1)


def test_prefill_patterns_cover_new_models() -> None:
    from livekit.plugins.anthropic import llm as lk_llm

    assert lk_llm._model_disables_prefill("claude-sonnet-4-6")
    assert lk_llm._model_disables_prefill("claude-sonnet-5-5")
    assert not lk_llm._model_disables_prefill("claude-haiku-4-5")
