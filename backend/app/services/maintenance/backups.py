from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from threading import RLock
from typing import Iterator
import zipfile

from app.core.config import Settings, get_settings
from app.version import APP_VERSION, BACKUP_FORMAT_VERSION


class BackupError(RuntimeError):
    pass


_lifecycle_lock = RLock()


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_revision(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
            row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            if not row:
                return None
            revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            return str(revision[0]) if revision else None
    except sqlite3.DatabaseError as exc:
        raise BackupError("Database could not be read for backup.") from exc


def _database_counts(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {}
    counts: dict[str, int] = {}
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (name,) in tables:
            safe_name = str(name).replace('"', '""')
            counts[str(name)] = int(connection.execute(f'SELECT COUNT(*) FROM "{safe_name}"').fetchone()[0])
    return counts


def _safe_database_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(source)) as source_connection, closing(sqlite3.connect(target)) as target_connection:
            source_connection.backup(target_connection)
        with closing(sqlite3.connect(target)) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError("Backup database failed its integrity check.")
    except sqlite3.DatabaseError as exc:
        raise BackupError("Database backup could not be created safely.") from exc


def _archive_files(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def _settings_metadata(settings: Settings) -> dict[str, object]:
    return {
        "automatic_backup_retention": settings.automatic_backup_retention,
        "max_upload_bytes": settings.max_upload_bytes,
    }


def create_backup(
    *,
    kind: str = "manual",
    label: str | None = None,
    settings: Settings | None = None,
) -> Path:
    settings = settings or get_settings()
    database_path = settings.database_path
    if database_path is None or not database_path.is_file():
        raise BackupError("No SQLite database is available to back up.")
    safe_kind = "automatic" if kind == "automatic" else "manual"
    safe_label = "".join(character if character.isalnum() or character in "-." else "-" for character in (label or ""))
    name_parts = ["personal-finance-backup", safe_kind]
    if safe_label:
        name_parts.append(safe_label.strip("-"))
    name_parts.append(_utc_stamp())
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.backups_dir / ("-".join(name_parts) + ".zip")

    with _lifecycle_lock, tempfile.TemporaryDirectory(prefix="pfm-backup-") as temporary:
        staging = Path(temporary)
        staged_database = staging / "data" / "finance.db"
        _safe_database_copy(database_path, staged_database)
        config_path = staging / "config" / "settings.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(_settings_metadata(settings), indent=2), encoding="utf-8")

        entries: list[tuple[Path, str]] = [(staged_database, "data/finance.db"), (config_path, "config/settings.json")]
        for source in _archive_files(settings.storage_dir):
            relative = source.relative_to(settings.storage_dir).as_posix()
            entries.append((source, f"storage/{relative}"))
        checksums = {archive_name: _sha256(source) for source, archive_name in entries}
        manifest = {
            "backup_version": BACKUP_FORMAT_VERSION,
            "app_version": APP_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": safe_kind,
            "database_schema_revision": _database_revision(staged_database),
            "files_included": True,
            "storage_file_count": sum(1 for _, name in entries if name.startswith("storage/")),
            "table_counts": _database_counts(staged_database),
            "checksums": checksums,
        }
        temporary_zip = destination.with_suffix(".tmp")
        try:
            with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                for source, archive_name in entries:
                    archive.write(source, archive_name)
            temporary_zip.replace(destination)
            validate_backup(destination)
        except Exception:
            temporary_zip.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    if safe_kind == "automatic":
        automatic = sorted(settings.backups_dir.glob("personal-finance-backup-automatic-*.zip"), reverse=True)
        for expired in automatic[settings.automatic_backup_retention :]:
            expired.unlink(missing_ok=True)
    return destination


def _validate_member_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise BackupError("Backup contains an unsafe file path.")


def validate_backup(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = set(archive.namelist())
            for name in names:
                _validate_member_name(name)
            if "manifest.json" not in names or "data/finance.db" not in names:
                raise BackupError("Backup is missing its manifest or database.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("backup_version") != BACKUP_FORMAT_VERSION:
                raise BackupError("Backup format is not compatible with this application version.")
            if int(str(manifest.get("app_version", "0")).split(".")[0]) > int(APP_VERSION.split(".")[0]):
                raise BackupError("Backup was created by an incompatible newer application version.")
            checksums = manifest.get("checksums")
            if not isinstance(checksums, dict):
                raise BackupError("Backup checksums are missing.")
            for name, expected in checksums.items():
                if name not in names or hashlib.sha256(archive.read(name)).hexdigest() != expected:
                    raise BackupError("Backup content failed checksum validation.")
            with tempfile.TemporaryDirectory(prefix="pfm-validate-") as temporary:
                database = Path(temporary) / "finance.db"
                database.write_bytes(archive.read("data/finance.db"))
                with closing(sqlite3.connect(database)) as connection:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise BackupError("Backup database failed its integrity check.")
            return manifest
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, OSError) as exc:
        raise BackupError("Backup archive is invalid or unreadable.") from exc


@contextmanager
def _rollback_paths(database_path: Path, storage_dir: Path) -> Iterator[tuple[Path, Path]]:
    with tempfile.TemporaryDirectory(prefix="pfm-restore-rollback-") as temporary:
        rollback = Path(temporary)
        old_database = rollback / "finance.db"
        old_storage = rollback / "storage"
        if database_path.exists():
            shutil.copy2(database_path, old_database)
        if storage_dir.exists():
            shutil.copytree(storage_dir, old_storage)
        try:
            yield old_database, old_storage
        except Exception:
            if old_database.exists():
                database_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_database, database_path)
            if storage_dir.exists():
                shutil.rmtree(storage_dir)
            if old_storage.exists():
                shutil.copytree(old_storage, storage_dir)
            raise


def restore_backup(path: Path, *, settings: Settings | None = None) -> tuple[Path, dict]:
    settings = settings or get_settings()
    database_path = settings.database_path
    if database_path is None:
        raise BackupError("Restore is supported only for a local SQLite database.")
    manifest = validate_backup(path)
    with _lifecycle_lock:
        safety_backup = create_backup(kind="automatic", label="pre-restore", settings=settings)
        with tempfile.TemporaryDirectory(prefix="pfm-restore-stage-") as temporary:
            staging = Path(temporary)
            with zipfile.ZipFile(path, "r") as archive:
                for name in archive.namelist():
                    _validate_member_name(name)
                    if name == "data/finance.db" or name.startswith("storage/"):
                        archive.extract(name, staging)
            staged_database = staging / "data" / "finance.db"
            staged_storage = staging / "storage"
            from app.db.session import get_engine, get_session_factory

            get_session_factory.cache_clear()
            get_engine().dispose()
            get_engine.cache_clear()
            with _rollback_paths(database_path, settings.storage_dir):
                database_path.parent.mkdir(parents=True, exist_ok=True)
                replacement = database_path.with_suffix(".restore")
                shutil.copy2(staged_database, replacement)
                replacement.replace(database_path)
                next_storage = settings.storage_dir.with_name(settings.storage_dir.name + ".restore")
                if next_storage.exists():
                    shutil.rmtree(next_storage)
                if staged_storage.exists():
                    shutil.copytree(staged_storage, next_storage)
                else:
                    next_storage.mkdir(parents=True)
                if settings.storage_dir.exists():
                    shutil.rmtree(settings.storage_dir)
                next_storage.replace(settings.storage_dir)
                with closing(sqlite3.connect(database_path)) as connection:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise BackupError("Restored database failed its integrity check.")
            get_session_factory.cache_clear()
            get_engine.cache_clear()
    return safety_backup, manifest


def restore_database_only(path: Path, *, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    database_path = settings.database_path
    if database_path is None:
        raise BackupError("Database recovery requires SQLite.")
    validate_backup(path)
    from app.db.session import get_engine, get_session_factory

    get_session_factory.cache_clear()
    get_engine().dispose()
    get_engine.cache_clear()
    with zipfile.ZipFile(path, "r") as archive:
        replacement = database_path.with_suffix(".rollback")
        replacement.write_bytes(archive.read("data/finance.db"))
        replacement.replace(database_path)
