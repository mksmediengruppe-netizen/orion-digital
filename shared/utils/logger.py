"""
ARCANE Logger
Structured JSON logging for all components.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Outputs log records as single-line JSON for easy parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat() + "Z",
            "level": record.levelname,
            "module": record.module,
            "func": record.funcName,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False, default=str)


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Create a named logger with JSON output."""
    logger = logging.getLogger(f"arcane.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    return logger


def log_with_data(logger: logging.Logger, level: str, msg: str, **kwargs: Any) -> None:
    """Log a message with structured extra data."""
    record = logger.makeRecord(
        logger.name,
        getattr(logging, level.upper()),
        "(unknown)",
        0,
        msg,
        (),
        None,
    )
    record.extra_data = kwargs
    logger.handle(record)
