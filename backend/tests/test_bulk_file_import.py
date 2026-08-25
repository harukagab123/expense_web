from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.models.file import StoredFile
from app.models.folder import Folder
from app.models.statement import Statement
from app.models.transaction import Transaction
from app.services.bulk_file_import import (
    SourceSpec,
    SourceValidationError,
    replace_file_manager_contents,
)


PDF_BYTES = b"%PDF-1.4\n%%EOF"


def _write_file(path: Path, content: bytes = PDF_BYTES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _create_old_managed_content() -> Path:
    settings = get_settings()
    storage_dir = settings.storage_dir
    storage_dir.mkdir(parents=True, exist_ok=True)
    old_physical_path = storage_dir / "old-managed.pdf"
    old_physical_path.write_bytes(PDF_BYTES)

    with get_session_factory()() as session:
        old_folder = Folder(name="Old Folder", parent_folder_id=None)
        session.add(old_folder)
        session.flush()
        old_file = StoredFile(
            folder_id=old_folder.id,
            original_filename="old-managed.pdf",
            display_name="old-managed.pdf",
            stored_filename="old-managed.pdf",
            storage_path="old-managed.pdf",
            mime_type="application/pdf",
            file_size=len(PDF_BYTES),
        )
        statement = Statement(file=old_file, document_type="BANK_STATEMENT", institution="CHASE")
        transaction = Transaction(
            statement=statement,
            transaction_date=date(2026, 8, 1),
            transaction_detail="Old transaction",
            amount=Decimal("12.34"),
            direction="OUTFLOW",
            source_order=1,
        )
        session.add_all([old_file, statement, transaction])
        session.commit()

    return old_physical_path


def _logical_paths() -> set[tuple[str, ...]]:
    with get_session_factory()() as session:
        folders = list(session.execute(select(Folder)).scalars().all())
        files = list(session.execute(select(StoredFile)).scalars().all())
    folder_by_id = {folder.id: folder for folder in folders}
    paths: set[tuple[str, ...]] = set()

    for stored_file in files:
        chain: list[str] = [stored_file.display_name]
        current = folder_by_id.get(stored_file.folder_id) if stored_file.folder_id is not None else None
        while current is not None:
            chain.append(current.name)
            current = folder_by_id.get(current.parent_folder_id) if current.parent_folder_id is not None else None
        paths.add(tuple(reversed(chain)))

    return paths


def _count(model: type[object]) -> int:
    with get_session_factory()() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture(autouse=True)
def _create_schema(temp_database_url: str) -> None:
    assert temp_database_url.startswith("sqlite:///")
    Base.metadata.create_all(bind=get_engine())


def test_replace_file_manager_contents_imports_recursive_sources_and_clears_old_data(tmp_path: Path) -> None:
    old_physical_path = _create_old_managed_content()
    source_a = tmp_path / "SourceA"
    source_b = tmp_path / "SourceB"
    _write_file(source_a / "Folder1" / "File1.pdf")
    _write_file(source_a / "Folder1" / "File2.pdf")
    _write_file(source_a / "Folder2" / "Nested" / "File3.pdf")
    _write_file(source_b / "Folder3" / "File4.pdf")

    with get_session_factory()() as session:
        report = replace_file_manager_contents(session, [SourceSpec(source_a), SourceSpec(source_b)])

    assert not report.has_failures
    assert report.old_counts.folders == 1
    assert report.old_counts.files == 1
    assert report.old_counts.statements == 1
    assert report.old_counts.transactions == 1
    assert report.new_counts.folders == 6
    assert report.new_counts.files == 4
    assert report.new_counts.statements == 0
    assert report.new_counts.transactions == 0
    assert not old_physical_path.exists()
    assert _count(Statement) == 0
    assert _count(Transaction) == 0

    assert _logical_paths() == {
        ("SourceA", "Folder1", "File1.pdf"),
        ("SourceA", "Folder1", "File2.pdf"),
        ("SourceA", "Folder2", "Nested", "File3.pdf"),
        ("SourceB", "Folder3", "File4.pdf"),
    }

    with get_session_factory()() as session:
        stored_files = list(session.execute(select(StoredFile)).scalars().all())
    for stored_file in stored_files:
        assert (get_settings().storage_dir / stored_file.storage_path).exists()

    assert (source_a / "Folder1" / "File1.pdf").exists()
    assert (source_b / "Folder3" / "File4.pdf").exists()


def test_missing_source_does_not_clear_existing_managed_files(tmp_path: Path) -> None:
    old_physical_path = _create_old_managed_content()
    valid_source = tmp_path / "SourceA"
    missing_source = tmp_path / "MissingSource"
    _write_file(valid_source / "Folder1" / "File1.pdf")

    with get_session_factory()() as session:
        with pytest.raises(SourceValidationError):
            replace_file_manager_contents(session, [SourceSpec(valid_source), SourceSpec(missing_source)])

    assert old_physical_path.exists()
    assert _count(Folder) == 1
    assert _count(StoredFile) == 1
    assert _count(Statement) == 1
    assert _count(Transaction) == 1
