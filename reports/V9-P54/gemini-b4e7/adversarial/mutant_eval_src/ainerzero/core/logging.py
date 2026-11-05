"""Bounded UTF-8 JSONL logs; secrets belong in neither messages nor fields."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_CONFIGURATION_LOCK = threading.Lock()
_SENSITIVE = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "apikey",
    "credential",
    "cookie",
    "privatekey",
    "accesskey",
)
_REDACTED = "[REDACTED]"


def _safe_fields(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            key = str(key)
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            result[key] = (
                _REDACTED if any(word in normalized for word in _SENSITIVE) else _safe_fields(child)
            )
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_fields(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class _JsonFormatter(logging.Formatter):
    def __init__(self, run_id: str | None) -> None:
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload = {
            "schema_version": 1,
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "event": str(getattr(record, "event", message)),
            "message": message,
            "run_id": self.run_id,
            "fields": _safe_fields(getattr(record, "fields", {})),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def configure_logging(log_path: Path, run_id: str | None = None) -> logging.Logger:
    """Return an isolated INFO logger, reusing one handler for the same file.

    ``logger.info('step completed', extra={'event': 'training.step',
    'fields': {'loss': 0.1}})`` writes one JSON record. Sensitive field keys are
    redacted recursively. Freeform messages and tracebacks must not include
    credentials: arbitrary secret text cannot be reliably identified.
    """
    log_path = Path(log_path).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(str(log_path).encode("utf-8")).hexdigest()[:20]
    logger = logging.getLogger(f"ainerzero.file.{identity}")
    with _CONFIGURATION_LOCK:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = next(
            (item for item in logger.handlers if getattr(item, "_ainerzero_owned", False)),
            None,
        )
        if handler is None:
            handler = RotatingFileHandler(
                log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
            handler._ainerzero_owned = True
            logger.addHandler(handler)
        handler.setFormatter(_JsonFormatter(run_id))
    return logger
