import json
import logging

from app.logging import configure_logging, log_context


def test_json_log_with_context(capsys) -> None:
    configure_logging("INFO")
    with log_context(attempt_id="a1", campaign_id="c1"):
        logging.getLogger("maria.test").info("dialing")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(line)
    assert data["message"] == "dialing"
    assert data["attempt_id"] == "a1"
    assert data["campaign_id"] == "c1"
    assert data["level"] == "INFO"
