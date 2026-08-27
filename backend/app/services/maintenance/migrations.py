from __future__ import annotations

from pathlib import Path
from contextlib import closing
import shutil
import sqlite3

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.core.resources import bundled_path
from app.services.maintenance.backups import BackupError, create_backup, restore_database_only


class MigrationError(RuntimeError):
    pass


def alembic_config(settings: Settings | None = None) -> Config:
    settings = settings or get_settings()
    ini_path = bundled_path("backend", "alembic.ini")
    migrations_path = bundled_path("backend", "migrations")
    config = Config(str(ini_path) if ini_path.exists() else None)
    config.set_main_option("script_location", str(migrations_path))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    return config


def required_revision(settings: Settings | None = None) -> str:
    return str(ScriptDirectory.from_config(alembic_config(settings)).get_current_head())


def current_revision(settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    path = settings.database_path
    if path is None or not path.exists():
        return None
    try:
        from sqlalchemy import create_engine

        engine = create_engine(settings.database_url)
        try:
            with engine.connect() as connection:
                return MigrationContext.configure(connection).get_current_revision()
        finally:
            engine.dispose()
    except (sqlite3.DatabaseError, SQLAlchemyError) as exc:
        raise MigrationError("Database could not be opened. It was preserved for recovery.") from exc


def migrate_database(*, settings: Settings | None = None) -> Path | None:
    settings = settings or get_settings()
    target = required_revision(settings)
    current = current_revision(settings)
    if current == target:
        return None
    backup: Path | None = None
    database_path = settings.database_path
    database_existed = bool(database_path and database_path.exists())
    if database_existed:
        try:
            backup = create_backup(kind="automatic", label=f"pre-migration-{current or 'legacy'}-to-{target}", settings=settings)
        except BackupError as exc:
            raise MigrationError("Migration stopped because its safety backup failed.") from exc
    try:
        command.upgrade(alembic_config(settings), "head")
        if current_revision(settings) != target:
            raise MigrationError("Migration did not reach the required schema revision.")
    except Exception as exc:
        if backup:
            restore_database_only(backup, settings=settings)
        elif not database_existed and database_path and database_path.exists():
            failed = database_path.with_suffix(".failed-migration")
            shutil.move(database_path, failed)
        raise MigrationError("Update could not be completed. Previous data was restored.") from exc
    return backup
