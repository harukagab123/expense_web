from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine, get_session_factory
from app.models.transaction import Transaction
from app.models.file import StoredFile
from app.models.statement import Statement
from app.services.maintenance.backups import BackupError, create_backup, restore_backup, validate_backup
from app.services.maintenance.diagnostics import create_diagnostic_bundle
from app.services.maintenance.health import maintenance_status
from app.services.maintenance.migrations import MigrationError, migrate_database, required_revision
from app.services.maintenance.startup import initialize_directories
from app.services.maintenance.startup import migrate_legacy_data, prepare_application


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_production_configuration_uses_per_user_data_directories(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PFM_DATA_DIR", str(tmp_path / "PersonalFinanceManager"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("STORAGE_DIR", raising=False)
    monkeypatch.delenv("BACKUPS_DIR", raising=False)
    monkeypatch.delenv("LOGS_DIR", raising=False)
    monkeypatch.delenv("CONFIG_DIR", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    initialize_directories(settings)

    assert settings.database_path == (tmp_path / "PersonalFinanceManager" / "data" / "finance.db").resolve()
    assert settings.storage_dir == tmp_path / "PersonalFinanceManager" / "storage"
    assert all(path.is_dir() for path in (
        settings.data_dir, settings.storage_dir, settings.backups_dir, settings.logs_dir, settings.config_dir
    ))
    get_settings.cache_clear()


def test_backup_zip_manifest_integrity_storage_and_retention(client: TestClient, monkeypatch) -> None:
    uploaded = client.post("/api/files", files=[("files", ("synthetic.txt", b"retained file", "text/plain"))])
    assert uploaded.status_code == 200
    settings = get_settings()
    object.__setattr__(settings, "automatic_backup_retention", 2)

    manual = create_backup(kind="manual")
    manifest = validate_backup(manual)
    assert manifest["app_version"] == "1.0.1"
    assert manifest["storage_file_count"] == 1
    assert "files" in manifest["table_counts"]
    with zipfile.ZipFile(manual) as archive:
        assert {"manifest.json", "data/finance.db", "config/settings.json"} <= set(archive.namelist())
        assert any(name.startswith("storage/") for name in archive.namelist())

    for index in range(4):
        create_backup(kind="automatic", label=f"retention-{index}")
    assert len(list(settings.backups_dir.glob("personal-finance-backup-automatic-*.zip"))) == 2
    assert manual.exists()


def test_backup_restore_round_trip_preserves_phase9_state_and_total(client: TestClient) -> None:
    from tests.test_expense_summary_api import populate_summary_fixture

    keys = populate_summary_fixture()
    before = client.get("/api/summary?tax_year=2026").json()
    assert before["grand_total"] == "4135.00"
    with get_session_factory()() as session:
        selected_before = {key: session.get(Transaction, value).include_in_expenses for key, value in keys.items()}
    backup = create_backup(kind="manual")

    changed = client.patch(f"/api/transactions/{keys['materials']}", json={"amount": "999.00"})
    client.patch(f"/api/transactions/{keys['office']}/inclusion", json={"include_in_expenses": False})
    assert changed.status_code == 200
    safety, manifest = restore_backup(backup)

    after = client.get("/api/summary?tax_year=2026").json()
    with get_session_factory()() as session:
        selected_after = {key: session.get(Transaction, value).include_in_expenses for key, value in keys.items()}
    assert safety.exists()
    assert manifest["table_counts"]["transactions"] == len(keys)
    assert after["grand_total"] == before["grand_total"] == "4135.00"
    assert selected_after == selected_before
    assert sum(1 for key in keys if selected_after[key] != selected_before[key]) == 0


def test_invalid_restore_never_modifies_current_database(client: TestClient, tmp_path) -> None:
    client.post("/api/folders", json={"name": "Preserved", "parent_folder_id": None})
    database = get_settings().database_path
    assert database is not None
    before = _file_hash(database)
    invalid = tmp_path / "invalid.zip"
    invalid.write_bytes(b"not a zip")

    with pytest.raises(BackupError):
        restore_backup(invalid)

    assert _file_hash(database) == before


def test_maintenance_api_requires_restore_confirmation_and_reports_health(client: TestClient) -> None:
    status = client.get("/api/maintenance/status?integrity=true")
    denied = client.post(
        "/api/maintenance/restore",
        data={"confirm": "false"},
        files={"backup": ("backup.zip", b"invalid", "application/zip")},
    )
    backup = client.post("/api/maintenance/backups")
    diagnostics = client.post("/api/maintenance/diagnostics")

    assert status.status_code == 200
    assert status.json()["database"]["status"] == "healthy"
    assert denied.status_code == 400
    assert backup.status_code == 200 and backup.content.startswith(b"PK")
    assert diagnostics.status_code == 200 and diagnostics.content.startswith(b"PK")


def test_diagnostic_bundle_excludes_financial_data_and_redacts_logs(client: TestClient) -> None:
    settings = get_settings()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    sensitive = "account number 1234567890123456 balance $9,999.00 transaction detail: PRIVATE MERCHANT"
    (settings.logs_dir / "application.log").write_text(sensitive, encoding="utf-8")
    bundle = create_diagnostic_bundle()

    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        contents = "\n".join(archive.read(name).decode("utf-8", errors="replace") for name in names)
    assert "finance.db" not in names
    assert not any(name.startswith("storage/") for name in names)
    assert "1234567890123456" not in contents
    assert "9,999.00" not in contents
    assert "PRIVATE MERCHANT" not in contents
    assert "[REDACTED]" in contents


def test_log_redaction_filter_and_rotation_configuration(temp_database_url, monkeypatch) -> None:
    from app.core.logging import SensitiveDataFilter

    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "account 1234567890123456 balance $500.00", (), None)
    assert SensitiveDataFilter().filter(record)
    assert "1234567890123456" not in record.getMessage()
    assert "$500.00" not in record.getMessage()


def test_migration_failure_restores_user_state_and_stops(client: TestClient, monkeypatch) -> None:
    folder = client.post("/api/folders", json={"name": "Migration State", "parent_folder_id": None}).json()
    target = required_revision()
    prior = "202608260011"
    with get_engine().begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version(version_num) VALUES (:revision)"), {"revision": prior})

    def fail_upgrade(*_args, **_kwargs):
        raise RuntimeError("synthetic migration failure")

    monkeypatch.setattr("app.services.maintenance.migrations.command.upgrade", fail_upgrade)
    with pytest.raises(MigrationError, match="Previous data was restored"):
        migrate_database()

    get_session_factory.cache_clear()
    get_engine.cache_clear()
    with get_engine().connect() as connection:
        preserved = connection.execute(text("SELECT name FROM folders WHERE id=:id"), {"id": folder["id"]}).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert preserved == "Migration State"
    assert revision == prior and revision != target
    assert list(get_settings().backups_dir.glob("*pre-migration*.zip"))


def test_missing_storage_is_reported_without_treating_database_as_corrupt(client: TestClient) -> None:
    settings = get_settings()
    if settings.storage_dir.exists():
        settings.storage_dir.rmdir()
    status = maintenance_status(integrity=True)
    assert status["database"]["status"] == "healthy"
    assert status["storage"]["status"] == "missing"


def test_first_run_and_existing_user_startup_apply_migrations_once(temp_database_url: str) -> None:
    settings = get_settings()
    assert settings.database_path is not None and not settings.database_path.exists()
    first_backup = prepare_application(settings)
    assert first_backup is None
    assert settings.database_path.exists()
    assert maintenance_status(integrity=True)["database"]["schema_revision"] == required_revision()

    second_backup = prepare_application(settings)
    assert second_backup is None
    assert maintenance_status(integrity=True)["database"]["status"] == "healthy"


def test_version_update_creates_backup_and_preserves_mixed_selections(
    temp_database_url: str,
) -> None:
    settings = get_settings()
    assert prepare_application(settings) is None
    settings_metadata = settings.config_dir / "settings.json"
    settings_metadata.write_text(
        json.dumps({"app_version": "1.0.0", "automatic_backup_retention": 10}),
        encoding="utf-8",
    )

    with get_session_factory()() as session:
        statement = Statement(
            file=StoredFile(
                original_filename="upgrade-synthetic.pdf",
                display_name="upgrade-synthetic.pdf",
                stored_filename="upgrade-synthetic.pdf",
                storage_path="upgrade-synthetic.pdf",
                mime_type="application/pdf",
                file_size=1,
            ),
            document_type="BANK_STATEMENT",
            institution="SYNTHETIC",
            account_type="CHECKING",
            statement_start_date=date(2026, 1, 1),
            statement_end_date=date(2026, 12, 31),
            detection_status="DETECTED",
        )
        session.add(statement)
        session.flush()
        selected = Transaction(
            statement=statement,
            transaction_date=date(2026, 1, 1),
            transaction_detail="UPGRADE SELECTED SYNTHETIC",
            amount=Decimal("10.00"),
            direction="OUTFLOW",
            source_order=1,
            transaction_type="EXPENSE",
            main_category="AUTO_EXPENSE",
            subcategory="AUTO_GAS",
            category_status="CATEGORIZED",
            include_in_expenses=True,
            inclusion_initialized=True,
        )
        unselected = Transaction(
            statement=statement,
            transaction_date=date(2026, 1, 2),
            transaction_detail="UPGRADE UNSELECTED SYNTHETIC",
            amount=Decimal("20.00"),
            direction="OUTFLOW",
            source_order=2,
            transaction_type="EXPENSE",
            main_category="PROFIT_LOSS_BUSINESS",
            subcategory="BUSINESS_OFFICE_EXPENSE",
            category_status="CATEGORIZED",
            include_in_expenses=False,
            inclusion_initialized=True,
        )
        session.add_all((selected, unselected))
        session.commit()
        transaction_ids = (selected.id, unselected.id)

    backup = prepare_application(settings)

    assert backup is not None
    assert "pre-update-1.0.0-to-1.0.1" in backup.name
    assert json.loads(settings_metadata.read_text(encoding="utf-8"))["app_version"] == "1.0.1"
    with get_session_factory()() as session:
        assert [session.get(Transaction, transaction_id).include_in_expenses for transaction_id in transaction_ids] == [
            True,
            False,
        ]


def test_corrupt_database_is_preserved_instead_of_reinitialized(temp_database_url: str) -> None:
    settings = get_settings()
    assert settings.database_path is not None
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    original = b"synthetic corrupt database - preserve for recovery"
    settings.database_path.write_bytes(original)

    with pytest.raises(MigrationError, match="preserved"):
        prepare_application(settings)

    assert settings.database_path.read_bytes() == original


def test_backup_failure_prevents_pending_migration(client: TestClient, monkeypatch) -> None:
    with get_engine().begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version(version_num) VALUES ('202608260011')"))
    called = False

    def should_not_upgrade(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("app.services.maintenance.migrations.create_backup", lambda **_kwargs: (_ for _ in ()).throw(BackupError("synthetic")))
    monkeypatch.setattr("app.services.maintenance.migrations.command.upgrade", should_not_upgrade)

    with pytest.raises(MigrationError, match="safety backup failed"):
        migrate_database()
    assert called is False


def test_duplicate_launcher_opens_existing_application(monkeypatch) -> None:
    from app import launcher

    opened: list[str] = []
    monkeypatch.setattr(launcher, "_mutex_is_duplicate", lambda: (True, object()))
    monkeypatch.setattr(launcher, "_existing_port", lambda: 8765)
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)

    assert launcher.main() == 0
    assert opened == ["http://127.0.0.1:8765/"]


def test_rotating_log_handler_limits_retained_files(tmp_path) -> None:
    from logging.handlers import RotatingFileHandler

    logger = logging.getLogger("phase10.rotation")
    logger.handlers.clear()
    logger.propagate = False
    handler = RotatingFileHandler(tmp_path / "application.log", maxBytes=128, backupCount=2, encoding="utf-8")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    for index in range(100):
        logger.info("synthetic safe diagnostic line %s", index)
    handler.close()
    logger.handlers.clear()
    assert len(list(tmp_path.glob("application.log*"))) <= 3


def test_legacy_data_migration_copies_and_verifies_without_deleting_old_data(tmp_path, monkeypatch) -> None:
    legacy_root = tmp_path / "legacy-app"
    legacy_database = legacy_root / "data" / "app.db"
    legacy_storage = legacy_root / "storage" / "files"
    legacy_database.parent.mkdir(parents=True)
    legacy_storage.mkdir(parents=True)
    connection = sqlite3.connect(legacy_database)
    try:
        connection.execute("CREATE TABLE preserved_state (value TEXT NOT NULL)")
        connection.execute("INSERT INTO preserved_state VALUES ('safe')")
        connection.commit()
    finally:
        connection.close()
    (legacy_storage / "one.pdf").write_bytes(b"one")
    (legacy_storage / "two.pdf").write_bytes(b"two")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PFM_DATA_DIR", str(tmp_path / "production-data"))
    for name in ("DATABASE_URL", "STORAGE_DIR", "BACKUPS_DIR", "LOGS_DIR", "CONFIG_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("app.services.maintenance.startup.SOURCE_ROOT", legacy_root)
    get_settings.cache_clear()
    settings = get_settings()
    initialize_directories(settings)

    assert migrate_legacy_data(settings) is True
    assert settings.database_path is not None and settings.database_path.exists()
    assert sorted(path.name for path in settings.storage_dir.iterdir()) == ["one.pdf", "two.pdf"]
    assert legacy_database.exists() and len(list(legacy_storage.iterdir())) == 2
    get_settings.cache_clear()


def test_frozen_release_discovers_only_the_nearby_repository_layout(tmp_path, monkeypatch) -> None:
    from app.services.maintenance import startup

    release = tmp_path / "project" / "outputs" / "release"
    release.mkdir(parents=True)
    executable = release / "PersonalFinanceManager.exe"
    executable.touch()
    monkeypatch.setattr(startup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(startup.sys, "executable", str(executable))
    monkeypatch.delenv("PFM_LEGACY_ROOT", raising=False)

    assert startup._legacy_roots() == [release.resolve(), (tmp_path / "project").resolve()]
