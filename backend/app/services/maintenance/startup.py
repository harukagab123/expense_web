from __future__ import annotations

import json
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from app.core.config import Settings, get_settings
from app.core.resources import SOURCE_ROOT
from app.services.maintenance.migrations import migrate_database
from app.version import APP_VERSION


def initialize_directories(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    for path in (settings.data_dir, settings.storage_dir, settings.backups_dir, settings.logs_dir, settings.config_dir):
        path.mkdir(parents=True, exist_ok=True)
    metadata = settings.config_dir / "settings.json"
    if not metadata.exists():
        metadata.write_text(
            json.dumps({"app_version": APP_VERSION, "automatic_backup_retention": settings.automatic_backup_retention}, indent=2),
            encoding="utf-8",
        )


def _legacy_roots() -> list[Path]:
    if os.getenv("PFM_SKIP_LEGACY_MIGRATION", "").strip() == "1":
        return []
    roots: list[Path] = []
    configured = os.getenv("PFM_LEGACY_ROOT", "").strip()
    if configured:
        roots.append(Path(configured).expanduser())
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        roots.append(executable_dir)
        if executable_dir.name.casefold() == "release" and executable_dir.parent.name.casefold() == "outputs":
            roots.append(executable_dir.parent.parent)
    else:
        roots.append(SOURCE_ROOT)
    unique: list[Path] = []
    for root in roots:
        resolved = root.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def migrate_legacy_data(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if settings.app_env.lower() != "production" or settings.database_path is None:
        return False
    target_database = settings.database_path
    legacy_root = next((root for root in _legacy_roots() if (root / "data" / "app.db").is_file()), None)
    if target_database.exists() or legacy_root is None:
        return False
    legacy_database = legacy_root / "data" / "app.db"
    legacy_storage = legacy_root / "storage" / "files"
    if any(settings.storage_dir.iterdir()):
        return False
    staged_storage = settings.storage_dir.with_name(settings.storage_dir.name + ".legacy-copy")
    try:
        with closing(sqlite3.connect(f"file:{legacy_database.as_posix()}?mode=ro", uri=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
        target_database.parent.mkdir(parents=True, exist_ok=True)
        temporary_database = target_database.with_suffix(".legacy-copy")
        shutil.copy2(legacy_database, temporary_database)
        with closing(sqlite3.connect(temporary_database)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                temporary_database.unlink(missing_ok=True)
                return False
        temporary_database.replace(target_database)
        if legacy_storage.is_dir():
            if staged_storage.exists():
                shutil.rmtree(staged_storage)
            shutil.copytree(legacy_storage, staged_storage)
            legacy_count = sum(1 for path in legacy_storage.rglob("*") if path.is_file())
            copied_count = sum(1 for path in staged_storage.rglob("*") if path.is_file())
            if copied_count != legacy_count:
                raise OSError("Legacy storage verification failed")
            settings.storage_dir.rmdir()
            staged_storage.replace(settings.storage_dir)
        return True
    except (OSError, sqlite3.DatabaseError):
        target_database.unlink(missing_ok=True)
        if staged_storage.exists():
            shutil.rmtree(staged_storage, ignore_errors=True)
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        return False


def prepare_application(settings: Settings | None = None) -> Path | None:
    settings = settings or get_settings()
    initialize_directories(settings)
    migrate_legacy_data(settings)
    return migrate_database(settings=settings)
