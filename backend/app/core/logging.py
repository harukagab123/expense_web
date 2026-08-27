from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import re

from app.core.config import get_settings


class SensitiveDataFilter(logging.Filter):
    """Redact common financial identifiers from messages before they are written."""

    _patterns = (
        (re.compile(r"(?i)(account(?:\s+(?:number|no\.?))?\s*[:=#-]?\s*)\d{4,}"), r"\1[REDACTED]"),
        (re.compile(r"\b\d{12,19}\b"), "[REDACTED]"),
        (re.compile(r"(?i)(balance\s*[:=]?\s*)\$?[\d,]+(?:\.\d{2})?"), r"\1[REDACTED]"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern, replacement in self._patterns:
            message = pattern.sub(replacement, message)
        record.msg = message
        record.args = ()
        return True


def configure_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    if getattr(root, "_pfm_configured", False):
        return
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    redactor = SensitiveDataFilter()
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(redactor)
    root.handlers.clear()
    root.addHandler(stream)
    if settings.app_env.lower() == "production":
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        rotating = RotatingFileHandler(
            settings.logs_dir / "application.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        rotating.setFormatter(formatter)
        rotating.addFilter(redactor)
        root.addHandler(rotating)
    root.setLevel(settings.log_level)
    root._pfm_configured = True  # type: ignore[attr-defined]
