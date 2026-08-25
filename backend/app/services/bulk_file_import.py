from __future__ import annotations

from dataclasses import dataclass, field
from mimetypes import guess_type
from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.file import StoredFile
from app.models.folder import Folder
from app.models.statement import Statement
from app.models.transaction import Transaction, TransactionExtraction
from app.services.file_manager import validate_display_name, validate_supported_file

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class SourceSpec:
    source_path: Path
    destination_root_name: str | None = None


@dataclass(frozen=True)
class SourceFolderEntry:
    relative_parts: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.relative_parts[-1]


@dataclass(frozen=True)
class SourceFileEntry:
    source_path: Path
    folder_parts: tuple[str, ...]
    filename: str
    size: int
    mime_type: str

    @property
    def relative_parts(self) -> tuple[str, ...]:
        return (*self.folder_parts, self.filename)


@dataclass(frozen=True)
class SourceManifest:
    source_path: Path
    destination_root_name: str
    folders: tuple[SourceFolderEntry, ...]
    files: tuple[SourceFileEntry, ...]

    @property
    def folder_count(self) -> int:
        return 1 + len(self.folders)

    @property
    def file_count(self) -> int:
        return len(self.files)

    def logical_file_paths(self) -> set[tuple[str, ...]]:
        return {(self.destination_root_name, *file_entry.relative_parts) for file_entry in self.files}


@dataclass(frozen=True)
class SourceValidationIssue:
    source_path: Path
    relative_path: str
    error: str


class SourceValidationError(RuntimeError):
    def __init__(self, issues: list[SourceValidationIssue]) -> None:
        self.issues = issues
        message = "; ".join(f"{issue.source_path} :: {issue.relative_path}: {issue.error}" for issue in issues)
        super().__init__(message)


@dataclass(frozen=True)
class PreparedFileCopy:
    source: SourceFileEntry
    stored_filename: str
    storage_path: str
    staged_path: Path
    final_path: Path


@dataclass(frozen=True)
class DatabaseContentCounts:
    folders: int
    files: int
    statements: int
    transaction_extractions: int
    transactions: int


@dataclass(frozen=True)
class SourceImportResult:
    destination_root_name: str
    source_folder_count: int
    source_file_count: int
    imported_folder_count: int
    imported_file_count: int
    relative_paths_matched: int
    physical_files_present: int
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class BulkImportReport:
    source_manifests: tuple[SourceManifest, ...]
    old_counts: DatabaseContentCounts
    new_counts: DatabaseContentCounts
    source_results: tuple[SourceImportResult, ...]
    old_storage_cleanup_failures: tuple[str, ...] = ()

    @property
    def total_source_files(self) -> int:
        return sum(manifest.file_count for manifest in self.source_manifests)

    @property
    def total_source_folders(self) -> int:
        return sum(manifest.folder_count for manifest in self.source_manifests)

    @property
    def has_failures(self) -> bool:
        return bool(self.old_storage_cleanup_failures) or any(result.failures for result in self.source_results)


def _format_relative(parts: tuple[str, ...]) -> str:
    return "/".join(parts) if parts else "."


def _safe_sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, path.name.casefold())


def _http_error_detail(exc: HTTPException) -> str:
    return str(exc.detail)


def _validate_name(value: str, field_name: str) -> str:
    try:
        return validate_display_name(value, field_name)
    except HTTPException as exc:
        raise ValueError(_http_error_detail(exc)) from exc


def _validate_source_file(path: Path, folder_parts: tuple[str, ...], max_upload_bytes: int) -> SourceFileEntry:
    try:
        filename = validate_display_name(path.name, "Filename")
        validate_supported_file(filename)
    except HTTPException as exc:
        raise ValueError(_http_error_detail(exc)) from exc

    try:
        stat_result = path.stat()
    except OSError as exc:
        raise ValueError(f"File could not be inspected: {exc.strerror or exc}") from exc

    if stat_result.st_size > max_upload_bytes:
        raise ValueError("File exceeds the configured upload size limit.")

    try:
        with path.open("rb") as source_file:
            source_file.read(1)
    except OSError as exc:
        raise ValueError(f"File could not be opened: {exc.strerror or exc}") from exc

    return SourceFileEntry(
        source_path=path,
        folder_parts=folder_parts,
        filename=filename,
        size=stat_result.st_size,
        mime_type=guess_type(filename)[0] or "application/octet-stream",
    )


def scan_source_tree(source_spec: SourceSpec) -> SourceManifest:
    source_path = source_spec.source_path.expanduser().resolve()
    issues: list[SourceValidationIssue] = []
    folders: list[SourceFolderEntry] = []
    files: list[SourceFileEntry] = []
    max_upload_bytes = get_settings().max_upload_bytes

    if not source_path.exists():
        raise SourceValidationError([SourceValidationIssue(source_path, ".", "Source directory does not exist.")])
    if not source_path.is_dir():
        raise SourceValidationError([SourceValidationIssue(source_path, ".", "Source path is not a directory.")])

    try:
        destination_root_name = _validate_name(source_spec.destination_root_name or source_path.name, "Folder name")
    except ValueError as exc:
        raise SourceValidationError([SourceValidationIssue(source_path, ".", str(exc))]) from exc

    def walk(current_path: Path, folder_parts: tuple[str, ...]) -> None:
        try:
            children = sorted(current_path.iterdir(), key=_safe_sort_key)
        except OSError as exc:
            issues.append(
                SourceValidationIssue(
                    source_path,
                    _format_relative(folder_parts),
                    f"Directory could not be read: {exc.strerror or exc}",
                )
            )
            return

        for child in children:
            relative_parts = (*folder_parts, child.name)
            if child.is_dir():
                try:
                    folder_name = _validate_name(child.name, "Folder name")
                except ValueError as exc:
                    issues.append(SourceValidationIssue(source_path, _format_relative(relative_parts), str(exc)))
                    continue
                folders.append(SourceFolderEntry((*folder_parts, folder_name)))
                walk(child, (*folder_parts, folder_name))
                continue

            if child.is_file():
                try:
                    files.append(_validate_source_file(child, folder_parts, max_upload_bytes))
                except ValueError as exc:
                    issues.append(SourceValidationIssue(source_path, _format_relative(relative_parts), str(exc)))
                continue

            issues.append(SourceValidationIssue(source_path, _format_relative(relative_parts), "Not a regular file or folder."))

    walk(source_path, ())
    if issues:
        raise SourceValidationError(issues)

    return SourceManifest(
        source_path=source_path,
        destination_root_name=destination_root_name,
        folders=tuple(folders),
        files=tuple(files),
    )


def scan_source_trees(source_specs: list[SourceSpec]) -> tuple[SourceManifest, ...]:
    if not source_specs:
        raise SourceValidationError([SourceValidationIssue(Path("."), ".", "At least one source directory is required.")])
    return tuple(scan_source_tree(source_spec) for source_spec in source_specs)


def database_content_counts(session: Session) -> DatabaseContentCounts:
    return DatabaseContentCounts(
        folders=session.scalar(select(func.count()).select_from(Folder)) or 0,
        files=session.scalar(select(func.count()).select_from(StoredFile)) or 0,
        statements=session.scalar(select(func.count()).select_from(Statement)) or 0,
        transaction_extractions=session.scalar(select(func.count()).select_from(TransactionExtraction)) or 0,
        transactions=session.scalar(select(func.count()).select_from(Transaction)) or 0,
    )


def _storage_root() -> Path:
    root = get_settings().storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _copy_file(source_path: Path, target_path: Path, expected_size: int) -> None:
    copied = 0
    with source_path.open("rb") as source_file, target_path.open("wb") as target_file:
        while chunk := source_file.read(CHUNK_SIZE):
            copied += len(chunk)
            target_file.write(chunk)
    if copied != expected_size:
        raise OSError(f"Copied {copied} bytes, expected {expected_size} bytes.")


def _prepare_file_copies(manifests: tuple[SourceManifest, ...]) -> tuple[Path, tuple[PreparedFileCopy, ...]]:
    root = _storage_root()
    staging_dir = root / f".bulk-import-{uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=False)
    prepared: list[PreparedFileCopy] = []

    try:
        for manifest in manifests:
            for source_file in manifest.files:
                extension = source_file.source_path.suffix.lower()
                stored_filename = f"{uuid4().hex}{extension}"
                staged_path = staging_dir / stored_filename
                final_path = root / stored_filename
                if final_path.exists():
                    raise OSError(f"Storage filename collision: {stored_filename}")
                _copy_file(source_file.source_path, staged_path, source_file.size)
                prepared.append(
                    PreparedFileCopy(
                        source=source_file,
                        stored_filename=stored_filename,
                        storage_path=stored_filename,
                        staged_path=staged_path,
                        final_path=final_path,
                    )
                )
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    return staging_dir, tuple(prepared)


def _move_prepared_files(prepared_files: tuple[PreparedFileCopy, ...]) -> list[Path]:
    moved_paths: list[Path] = []
    for prepared in prepared_files:
        if prepared.final_path.exists():
            raise OSError(f"Storage filename collision: {prepared.stored_filename}")
        prepared.staged_path.replace(prepared.final_path)
        moved_paths.append(prepared.final_path)
    return moved_paths


def _cleanup_paths(paths: list[Path]) -> tuple[str, ...]:
    failures: list[str] = []
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            failures.append(f"{path.name}: {exc.strerror or exc}")
    return tuple(failures)


def _cleanup_old_storage_paths(old_storage_paths: list[str], new_storage_paths: set[str]) -> tuple[str, ...]:
    root = _storage_root()
    failures: list[str] = []
    for storage_path in old_storage_paths:
        if storage_path in new_storage_paths:
            continue
        candidate = (root / storage_path).resolve()
        if candidate == root or root not in candidate.parents:
            failures.append(f"{storage_path}: stored file location is invalid")
            continue
        try:
            candidate.unlink(missing_ok=True)
        except OSError as exc:
            failures.append(f"{storage_path}: {exc.strerror or exc}")
    return tuple(failures)


def _insert_manifest(
    session: Session,
    manifest: SourceManifest,
    prepared_by_source_path: dict[Path, PreparedFileCopy],
) -> None:
    root_folder = Folder(name=manifest.destination_root_name, parent_folder_id=None)
    session.add(root_folder)
    session.flush()
    folder_ids: dict[tuple[str, ...], int] = {(): root_folder.id}

    for folder_entry in manifest.folders:
        parent_parts = folder_entry.relative_parts[:-1]
        folder = Folder(name=folder_entry.name, parent_folder_id=folder_ids[parent_parts])
        session.add(folder)
        session.flush()
        folder_ids[folder_entry.relative_parts] = folder.id

    for source_file in manifest.files:
        prepared = prepared_by_source_path[source_file.source_path]
        session.add(
            StoredFile(
                folder_id=folder_ids[source_file.folder_parts],
                original_filename=source_file.filename,
                display_name=source_file.filename,
                stored_filename=prepared.stored_filename,
                storage_path=prepared.storage_path,
                mime_type=source_file.mime_type,
                file_size=source_file.size,
            )
        )


def _logical_file_paths_for_root(session: Session, root_name: str) -> set[tuple[str, ...]]:
    folders = list(session.execute(select(Folder)).scalars().all())
    files = list(session.execute(select(StoredFile)).scalars().all())
    folders_by_id = {folder.id: folder for folder in folders}
    root_folder_ids = {folder.id for folder in folders if folder.parent_folder_id is None and folder.name == root_name}
    paths: set[tuple[str, ...]] = set()

    for stored_file in files:
        if stored_file.folder_id is None:
            continue
        chain: list[str] = []
        current = folders_by_id.get(stored_file.folder_id)
        while current is not None:
            chain.append(current.name)
            if current.parent_folder_id is None:
                break
            current = folders_by_id.get(current.parent_folder_id)
        if current is None or current.id not in root_folder_ids:
            continue
        paths.add((*reversed(chain), stored_file.display_name))

    return paths


def _folder_count_for_root(session: Session, root_name: str) -> int:
    folders = list(session.execute(select(Folder)).scalars().all())
    children_by_parent: dict[int | None, list[Folder]] = {}
    for folder in folders:
        children_by_parent.setdefault(folder.parent_folder_id, []).append(folder)

    def count_descendants(folder_id: int) -> int:
        return 1 + sum(count_descendants(child.id) for child in children_by_parent.get(folder_id, []))

    return sum(
        count_descendants(folder.id)
        for folder in children_by_parent.get(None, [])
        if folder.name == root_name
    )


def _file_count_for_root(session: Session, root_name: str) -> int:
    folders = list(session.execute(select(Folder)).scalars().all())
    files = list(session.execute(select(StoredFile)).scalars().all())
    folder_by_id = {folder.id: folder for folder in folders}
    root_ids = {folder.id for folder in folders if folder.parent_folder_id is None and folder.name == root_name}
    count = 0

    for stored_file in files:
        current = folder_by_id.get(stored_file.folder_id) if stored_file.folder_id is not None else None
        while current is not None and current.parent_folder_id is not None:
            current = folder_by_id.get(current.parent_folder_id)
        if current is not None and current.id in root_ids:
            count += 1

    return count


def _physical_file_count_for_root(session: Session, root_name: str) -> int:
    root = _storage_root()
    folders = list(session.execute(select(Folder)).scalars().all())
    files = list(session.execute(select(StoredFile)).scalars().all())
    folder_by_id = {folder.id: folder for folder in folders}
    root_ids = {folder.id for folder in folders if folder.parent_folder_id is None and folder.name == root_name}
    count = 0

    for stored_file in files:
        current = folder_by_id.get(stored_file.folder_id) if stored_file.folder_id is not None else None
        while current is not None and current.parent_folder_id is not None:
            current = folder_by_id.get(current.parent_folder_id)
        if current is None or current.id not in root_ids:
            continue
        candidate = (root / stored_file.storage_path).resolve()
        if candidate != root and root in candidate.parents and candidate.exists():
            count += 1

    return count


def _verify_import(session: Session, manifests: tuple[SourceManifest, ...]) -> tuple[SourceImportResult, ...]:
    results: list[SourceImportResult] = []

    for manifest in manifests:
        expected_paths = manifest.logical_file_paths()
        actual_paths = _logical_file_paths_for_root(session, manifest.destination_root_name)
        matched_paths = expected_paths & actual_paths
        failures: list[str] = []

        missing_paths = sorted(expected_paths - actual_paths)
        extra_paths = sorted(actual_paths - expected_paths)
        if missing_paths:
            failures.append(f"Missing relative paths: {len(missing_paths)}")
        if extra_paths:
            failures.append(f"Extra relative paths: {len(extra_paths)}")

        imported_folder_count = _folder_count_for_root(session, manifest.destination_root_name)
        imported_file_count = _file_count_for_root(session, manifest.destination_root_name)
        physical_files_present = _physical_file_count_for_root(session, manifest.destination_root_name)

        if imported_folder_count != manifest.folder_count:
            failures.append(f"Folder count mismatch: {imported_folder_count} imported, {manifest.folder_count} expected")
        if imported_file_count != manifest.file_count:
            failures.append(f"File count mismatch: {imported_file_count} imported, {manifest.file_count} expected")
        if physical_files_present != manifest.file_count:
            failures.append(f"Physical file mismatch: {physical_files_present} present, {manifest.file_count} expected")

        results.append(
            SourceImportResult(
                destination_root_name=manifest.destination_root_name,
                source_folder_count=manifest.folder_count,
                source_file_count=manifest.file_count,
                imported_folder_count=imported_folder_count,
                imported_file_count=imported_file_count,
                relative_paths_matched=len(matched_paths),
                physical_files_present=physical_files_present,
                failures=tuple(failures),
            )
        )

    return tuple(results)


def replace_file_manager_contents(session: Session, source_specs: list[SourceSpec]) -> BulkImportReport:
    manifests = scan_source_trees(source_specs)
    old_counts = database_content_counts(session)
    old_storage_paths = list(session.execute(select(StoredFile.storage_path)).scalars().all())
    session.rollback()

    staging_dir, prepared_files = _prepare_file_copies(manifests)
    moved_paths: list[Path] = []
    prepared_by_source_path = {prepared.source.source_path: prepared for prepared in prepared_files}

    try:
        with session.begin():
            session.execute(delete(StoredFile))
            session.execute(delete(Folder))
            for manifest in manifests:
                _insert_manifest(session, manifest, prepared_by_source_path)
            moved_paths = _move_prepared_files(prepared_files)
    except Exception:
        session.rollback()
        _cleanup_paths(moved_paths)
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    old_storage_cleanup_failures = _cleanup_old_storage_paths(
        old_storage_paths,
        {prepared.storage_path for prepared in prepared_files},
    )
    new_counts = database_content_counts(session)
    source_results = _verify_import(session, manifests)

    return BulkImportReport(
        source_manifests=manifests,
        old_counts=old_counts,
        new_counts=new_counts,
        source_results=source_results,
        old_storage_cleanup_failures=old_storage_cleanup_failures,
    )
