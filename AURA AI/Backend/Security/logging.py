"""Structured redacting logs for operational events."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping

from .privacy import safe_metadata


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": int(time.time()),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        details = getattr(record, "details", None)
        if isinstance(details, Mapping):
            payload["details"] = safe_metadata(dict(details))
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def get_security_logger(name: str = "aura.security") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(RedactingJsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def security_event(logger: logging.Logger, event: str, details: Mapping[str, Any] | None = None, *, level: int = logging.INFO) -> None:
    logger.log(level, event, extra={"details": safe_metadata(dict(details or {}))})
