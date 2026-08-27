from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3

from app.core.config import Settings, get_settings
from app.version import APP_NAME, APP_VERSION


def _directory_size(path: Path) -> tuple[int, int]:
    count = 0
    size = 0
    if path.is_dir():
        for item in path.rglob("*"):
            if item.is_file():
                count += 1
                try:
                    size += item.stat().st_size
                except OSError:
                    pass
    return count, size


def _database_health(settings: Settings, *, integrity: bool) -> tuple[str, str | None]:
    path = settings.database_path
    if path is None:
        return "unavailable", None
    if not path.exists():
        return "not_initialized", None
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
            connection.execute("SELECT 1").fetchone()
            if integrity and connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return "unhealthy", None
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone() if table else None
        return "healthy", str(revision[0]) if revision else None
    except (sqlite3.DatabaseError, OSError):
        return "unhealthy", None


def maintenance_status(*, integrity: bool = False, settings: Settings | None = None) -> dict[str, object]:
    settings = settings or get_settings()
    database_status, revision = _database_health(settings, integrity=integrity)
    storage_count, storage_bytes = _directory_size(settings.storage_dir)
    backups = sorted(settings.backups_dir.glob("personal-finance-backup-*.zip"), key=lambda path: path.stat().st_mtime, reverse=True) if settings.backups_dir.is_dir() else []
    last_backup = None
    if backups:
        last_backup = datetime.fromtimestamp(backups[0].stat().st_mtime, tz=timezone.utc).isoformat()
    return {
        "application": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "status": "healthy" if database_status == "healthy" and settings.storage_dir.is_dir() else "attention",
        },
        "database": {"status": database_status, "schema_revision": revision},
        "storage": {
            "status": "healthy" if settings.storage_dir.is_dir() else "missing",
            "retained_file_count": storage_count,
            "size_bytes": storage_bytes,
        },
        "backup": {"last_successful_at": last_backup, "count": len(backups)},
        "paths": {
            "data": str(settings.data_dir),
            "storage": str(settings.storage_dir),
            "backups": str(settings.backups_dir),
            "logs": str(settings.logs_dir),
        },
    }
