"""Structured JSON logging. Call-path code binds attempt_id / campaign_id via `log_context`."""

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

_context: ContextVar[dict[str, object] | None] = ContextVar("log_context", default=None)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in (_context.get() or {}).items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


@contextmanager
def log_context(**fields: object) -> Iterator[None]:
    """Attach fields (e.g. attempt_id, campaign_id) to every log line in this context."""
    token = _context.set({**(_context.get() or {}), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
        )
    )
    handler.addFilter(_ContextFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
