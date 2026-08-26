from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.file import StoredFile
from app.models.folder import Folder
from app.models.statement import Statement
from app.models.transaction import Transaction
from app.services.source_retention import apply_retention_for_institution


def _create_source_statement(
    session,
    *,
    institution: str,
    display_name: str,
    statement_end_date: date | None,
    created_at: datetime,
    document_type: str = "BANK_STATEMENT",
    folder_id: int | None = None,
    with_transaction: bool = True,
) -> tuple[StoredFile, Statement]:
    storage_root = get_settings().storage_dir
    storage_root.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{institution.lower()}-{display_name.lower().replace(' ', '-')}"
    storage_path = Path(stored_filename).name
    (storage_root / storage_path).write_bytes(b"%PDF-1.4\n%%EOF")

    stored_file = StoredFile(
        folder_id=folder_id,
        original_filename=display_name,
        display_name=display_name,
        stored_filename=stored_filename,
        storage_path=storage_path,
        mime_type="application/pdf",
        file_size=14,
        source_file_available=True,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(stored_file)
    session.flush()

    statement = Statement(
        file_id=stored_file.id,
        document_type=document_type,
        institution=institution,
        account_type="CHECKING",
        statement_end_date=statement_end_date,
        detection_status="DETECTED",
        detection_confidence=1.0,
        detected_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(statement)
    session.flush()

    if with_transaction:
        transaction = Transaction(
            statement_id=statement.id,
            transaction_date=statement_end_date or date(2026, 1, 1),
            transaction_detail=f"{display_name} retained transaction",
            amount=Decimal("12.34"),
            direction="OUTFLOW",
            source_order=1,
            extraction_confidence=1.0,
            needs_review=False,
            user_edited=True,
            source="EXTRACTED",
            normalized_name="Retention Test",
            transaction_type="EXPENSE",
            type_status="USER_CONFIRMED",
            main_category="AUTO_EXPENSE",
            subcategory="AUTO_GAS",
            category_status="USER_CONFIRMED",
            include_in_expenses=False,
            inclusion_initialized=True,
            inclusion_source="USER_EXCLUDED",
            review_status="REVIEWED",
        )
        session.add(transaction)

    session.commit()
    session.refresh(stored_file)
    session.refresh(statement)
    return stored_file, statement


def _create_plain_source_file(session, display_name: str, created_at: datetime) -> StoredFile:
    storage_root = get_settings().storage_dir
    storage_root.mkdir(parents=True, exist_ok=True)
    storage_path = Path(display_name.lower().replace(" ", "-")).name
    (storage_root / storage_path).write_bytes(b"plain file")
    stored_file = StoredFile(
        original_filename=display_name,
        display_name=display_name,
        stored_filename=storage_path,
        storage_path=storage_path,
        mime_type="application/pdf",
        file_size=10,
        source_file_available=True,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(stored_file)
    session.commit()
    session.refresh(stored_file)
    return stored_file


def _path_for(stored_file: StoredFile) -> Path:
    return get_settings().storage_dir / stored_file.storage_path


def _available_statement_files(session, institution: str) -> list[StoredFile]:
    return [
        statement.file
        for statement in session.query(Statement)
        .filter(Statement.institution == institution)
        .order_by(Statement.statement_end_date.asc().nullsfirst(), Statement.id.asc())
        .all()
        if statement.file.source_file_available
    ]


def test_retention_keeps_first_five_statement_sources(client: TestClient) -> None:
    with get_session_factory()() as session:
        for month in range(1, 6):
            _create_source_statement(
                session,
                institution="CHASE",
                display_name=f"Chase 2026-{month:02d}.pdf",
                statement_end_date=date(2026, month, 28),
                created_at=datetime(2026, month, 28, tzinfo=UTC),
            )

        result = apply_retention_for_institution(session, "CHASE")

        assert result.removed_count == 0
        files = _available_statement_files(session, "CHASE")
        assert len(files) == 5
        assert all(file.source_file_available for file in files)
        assert all(_path_for(file).exists() for file in files)


def test_retention_removes_oldest_source_and_preserves_history(client: TestClient) -> None:
    with get_session_factory()() as session:
        created = [
            _create_source_statement(
                session,
                institution="CHASE",
                display_name=f"Chase 2026-{month:02d}.pdf",
                statement_end_date=date(2026, month, 28),
                created_at=datetime(2026, month, 28, tzinfo=UTC),
            )
            for month in range(1, 7)
        ]
        oldest_file, oldest_statement = created[0]
        oldest_file_id = oldest_file.id
        oldest_statement_id = oldest_statement.id
        oldest_transaction_id = oldest_statement.transactions[0].id
        oldest_path = _path_for(oldest_file)

        result = apply_retention_for_institution(session, "CHASE")
        session.expire_all()

        removed_file = session.get(StoredFile, oldest_file_id)
        statement = session.get(Statement, oldest_statement_id)
        transaction = session.get(Transaction, oldest_transaction_id)

        assert result.removed_count == 1
        assert removed_file is not None
        assert removed_file.source_file_available is False
        assert removed_file.source_file_removed_at is not None
        assert removed_file.source_file_removal_reason == "RETENTION_LIMIT"
        assert not oldest_path.exists()
        assert statement is not None
        assert transaction is not None
        assert transaction.main_category == "AUTO_EXPENSE"
        assert transaction.subcategory == "AUTO_GAS"
        assert transaction.include_in_expenses is False
        assert transaction.review_status == "REVIEWED"
        assert [file.display_name for file in _available_statement_files(session, "CHASE")] == [
            "Chase 2026-02.pdf",
            "Chase 2026-03.pdf",
            "Chase 2026-04.pdf",
            "Chase 2026-05.pdf",
            "Chase 2026-06.pdf",
        ]


def test_retention_counts_each_institution_independently(client: TestClient) -> None:
    with get_session_factory()() as session:
        for institution in ("CHASE", "AMEX"):
            for month in range(1, 7):
                _create_source_statement(
                    session,
                    institution=institution,
                    display_name=f"{institution} 2026-{month:02d}.pdf",
                    statement_end_date=date(2026, month, 28),
                    created_at=datetime(2026, month, 28, tzinfo=UTC),
                )

        chase_result = apply_retention_for_institution(session, "CHASE")
        amex_result = apply_retention_for_institution(session, "AMEX")

        assert chase_result.removed_count == 1
        assert amex_result.removed_count == 1
        assert len(_available_statement_files(session, "CHASE")) == 5
        assert len(_available_statement_files(session, "AMEX")) == 5


def test_retention_counts_each_statement_folder_independently(client: TestClient) -> None:
    with get_session_factory()() as session:
        folders = [Folder(name="Rica Chase"), Folder(name="Lawrence Chase")]
        session.add_all(folders)
        session.flush()

        for folder in folders:
            for month in range(1, 7):
                _create_source_statement(
                    session,
                    institution="CHASE",
                    display_name=f"{folder.name} 2026-{month:02d}.pdf",
                    statement_end_date=date(2026, month, 28),
                    created_at=datetime(2026, month, 28, tzinfo=UTC),
                    folder_id=folder.id,
                )

        result = apply_retention_for_institution(session, "CHASE")

        assert result.removed_count == 2
        for folder in folders:
            available_count = (
                session.query(StoredFile)
                .filter(
                    StoredFile.folder_id == folder.id,
                    StoredFile.source_file_available.is_(True),
                )
                .count()
            )
            assert available_count == 5


def test_retention_protects_non_statement_files(client: TestClient) -> None:
    with get_session_factory()() as session:
        for month in range(1, 7):
            _create_source_statement(
                session,
                institution="CHASE",
                display_name=f"Chase 2026-{month:02d}.pdf",
                statement_end_date=date(2026, month, 28),
                created_at=datetime(2026, month, 28, tzinfo=UTC),
            )
        plain_files = [
            _create_plain_source_file(session, "Notes.pdf", datetime(2026, 1, 1, tzinfo=UTC)),
            _create_plain_source_file(session, "RandomDocument.pdf", datetime(2026, 1, 2, tzinfo=UTC)),
            _create_plain_source_file(session, "TaxSummary.xlsx", datetime(2026, 1, 3, tzinfo=UTC)),
        ]

        result = apply_retention_for_institution(session, "CHASE")
        session.expire_all()

        assert result.removed_count == 1
        for plain_file in plain_files:
            reloaded = session.get(StoredFile, plain_file.id)
            assert reloaded is not None
            assert reloaded.source_file_available is True
            assert _path_for(reloaded).exists()


def test_retention_uses_upload_date_fallback_when_statement_dates_missing(client: TestClient) -> None:
    with get_session_factory()() as session:
        for month in range(1, 7):
            _create_source_statement(
                session,
                institution="CHASE",
                display_name=f"Chase upload {month}.pdf",
                statement_end_date=None,
                created_at=datetime(2026, month, 1, tzinfo=UTC),
                with_transaction=False,
            )

        result = apply_retention_for_institution(session, "CHASE")
        session.expire_all()

        assert result.removed_count == 1
        assert [file.display_name for file in _available_statement_files(session, "CHASE")] == [
            "Chase upload 2.pdf",
            "Chase upload 3.pdf",
            "Chase upload 4.pdf",
            "Chase upload 5.pdf",
            "Chase upload 6.pdf",
        ]


def test_removed_source_is_hidden_from_tree_and_preview_returns_gone(client: TestClient) -> None:
    with get_session_factory()() as session:
        created = [
            _create_source_statement(
                session,
                institution="CHASE",
                display_name=f"Chase 2026-{month:02d}.pdf",
                statement_end_date=date(2026, month, 28),
                created_at=datetime(2026, month, 28, tzinfo=UTC),
            )
            for month in range(1, 7)
        ]
        oldest_file_id = created[0][0].id
        apply_retention_for_institution(session, "CHASE")

    tree = client.get("/api/file-manager/tree")
    preview = client.get(f"/api/files/{oldest_file_id}/preview")
    download = client.get(f"/api/files/{oldest_file_id}/download")

    assert tree.status_code == 200, tree.text
    root_names = [file["display_name"] for file in tree.json()["files"]]
    assert "Chase 2026-01.pdf" not in root_names
    assert "Chase 2026-06.pdf" in root_names
    assert preview.status_code == 410
    assert download.status_code == 410


def test_retention_cleans_existing_nine_sources_to_five_without_losing_history(client: TestClient) -> None:
    with get_session_factory()() as session:
        created = [
            _create_source_statement(
                session,
                institution="CHASE",
                display_name=f"Chase backlog 2026-{month:02d}.pdf",
                statement_end_date=date(2026, month, 28),
                created_at=datetime(2026, month, 28, tzinfo=UTC),
            )
            for month in range(1, 10)
        ]
        transaction_ids = [statement.transactions[0].id for _, statement in created]

        result = apply_retention_for_institution(session, "CHASE")
        session.expire_all()

        assert result.removed_count == 4
        assert [file.display_name for file in _available_statement_files(session, "CHASE")] == [
            "Chase backlog 2026-05.pdf",
            "Chase backlog 2026-06.pdf",
            "Chase backlog 2026-07.pdf",
            "Chase backlog 2026-08.pdf",
            "Chase backlog 2026-09.pdf",
        ]
        historical_transactions = [session.get(Transaction, transaction_id) for transaction_id in transaction_ids]
        assert all(transaction is not None for transaction in historical_transactions)
        assert all(transaction.include_in_expenses is False for transaction in historical_transactions if transaction)
        assert all(transaction.review_status == "REVIEWED" for transaction in historical_transactions if transaction)
