from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
import zipfile

from app.core.config import Settings, get_settings
from app.services.maintenance.health import maintenance_status


_REDACTIONS = (
    (re.compile(r"(?i)(account(?:\s+(?:number|no\.?))?\s*[:=#-]?\s*)\d{4,}"), r"\1[REDACTED]"),
    (re.compile(r"\b\d{12,19}\b"), "[REDACTED]"),
    (re.compile(r"(?i)(balance\s*[:=]?\s*)\$?[\d,]+(?:\.\d{2})?"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(transaction(?:\s+detail)?\s*[:=]\s*)[^\r\n]+"), r"\1[REDACTED]"),
)


def sanitize_diagnostic_text(value: str) -> str:
    home = str(Path.home())
    sanitized = value.replace(home, "%USERPROFILE%").replace(home.replace("\\", "/"), "%USERPROFILE%")
    for pattern, replacement in _REDACTIONS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def create_diagnostic_bundle(*, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.backups_dir / f"personal-finance-diagnostics-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}.zip"
    status = maintenance_status(integrity=True, settings=settings)
    status["paths"] = {key: f"<{key}-directory>" for key in status["paths"]}
    with tempfile.TemporaryDirectory(prefix="pfm-diagnostics-") as temporary:
        root = Path(temporary)
        (root / "diagnostics.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        (root / "README.txt").write_text(
            "Personal Finance Manager diagnostic bundle. Financial database, statements, transactions, exports, and account data are intentionally excluded.\n",
            encoding="utf-8",
        )
        logs_target = root / "logs"
        logs_target.mkdir()
        if settings.logs_dir.is_dir():
            for log in settings.logs_dir.glob("*.log*"):
                if log.is_file():
                    text = log.read_text(encoding="utf-8", errors="replace")
                    (logs_target / log.name).write_text(sanitize_diagnostic_text(text), encoding="utf-8")
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(root.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(root).as_posix())
    return destination
