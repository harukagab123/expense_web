from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.file import StoredFile
from app.models.folder import Folder
from app.schemas.file_manager import FileTreeItem, FolderTreeNode, SearchResult

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".csv", ".xlsx", ".txt"}
PREVIEW_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
CHUNK_SIZE = 1024 * 1024
SOURCE_FILE_REMOVAL_RETENTION = "RETENTION_LIMIT"
_UNSET = object()


def validate_display_name(value: str, field_name: str = "name") -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status_code=400, detail=f"{field_name} is required.")
    if len(name) > 255:
        raise HTTPException(status_code=400, detail=f"{field_name} must be 255 characters or fewer.")
    if "\x00" in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot contain path separators.")
    if name in {".", ".."}:
        raise HTTPException(status_code=400, detail=f"{field_name} is not allowed.")
    return name


def get_folder_or_404(session: Session, folder_id: int) -> Folder:
    folder = session.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found.")
    return folder


def get_file_or_404(session: Session, file_id: int) -> StoredFile:
    stored_file = session.get(StoredFile, file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return stored_file


def validate_folder_parent(session: Session, parent_folder_id: int | None) -> Folder | None:
    if parent_folder_id is None:
        return None
    return get_folder_or_404(session, parent_folder_id)


def _folder_name_query(name: str, parent_folder_id: int | None) -> Select[tuple[Folder]]:
    statement = select(Folder).where(Folder.name == name)
    if parent_folder_id is None:
        return statement.where(Folder.parent_folder_id.is_(None))
    return statement.where(Folder.parent_folder_id == parent_folder_id)


def _file_name_query(display_name: str, folder_id: int | None) -> Select[tuple[StoredFile]]:
    statement = select(StoredFile).where(
        StoredFile.display_name == display_name,
        StoredFile.source_file_available.is_(True),
    )
    if folder_id is None:
        return statement.where(StoredFile.folder_id.is_(None))
    return statement.where(StoredFile.folder_id == folder_id)


def ensure_folder_name_available(
    session: Session,
    name: str,
    parent_folder_id: int | None,
    exclude_folder_id: int | None = None,
) -> None:
    statement = _folder_name_query(name, parent_folder_id)
    if exclude_folder_id is not None:
        statement = statement.where(Folder.id != exclude_folder_id)
    if session.execute(statement).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="A folder with that name already exists here.")


def ensure_file_name_available(
    session: Session,
    display_name: str,
    folder_id: int | None,
    exclude_file_id: int | None = None,
) -> None:
    statement = _file_name_query(display_name, folder_id)
    if exclude_file_id is not None:
        statement = statement.where(StoredFile.id != exclude_file_id)
    if session.execute(statement).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="A file with that name already exists here.")


def create_folder(session: Session, name: str, parent_folder_id: int | None) -> Folder:
    safe_name = validate_display_name(name, "Folder name")
    validate_folder_parent(session, parent_folder_id)
    ensure_folder_name_available(session, safe_name, parent_folder_id)

    folder = Folder(name=safe_name, parent_folder_id=parent_folder_id)
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return folder


def _validate_no_folder_cycle(session: Session, folder_id: int, new_parent_id: int | None) -> None:
    if new_parent_id is None:
        return
    if folder_id == new_parent_id:
        raise HTTPException(status_code=400, detail="A folder cannot be moved into itself.")

    current = get_folder_or_404(session, new_parent_id)
    while current is not None:
        if current.id == folder_id:
            raise HTTPException(status_code=400, detail="A folder cannot be moved into its descendant.")
        current = current.parent


def update_folder(
    session: Session,
    folder_id: int,
    name: str | object = _UNSET,
    parent_folder_id: int | None | object = _UNSET,
) -> Folder:
    folder = get_folder_or_404(session, folder_id)
    if name is not _UNSET and name is None:
        raise HTTPException(status_code=400, detail="Folder name is required.")
    next_name = folder.name if name is _UNSET else validate_display_name(str(name), "Folder name")
    next_parent_id = folder.parent_folder_id if parent_folder_id is _UNSET else parent_folder_id

    if next_parent_id is not None and not isinstance(next_parent_id, int):
        raise HTTPException(status_code=400, detail="Invalid parent folder.")
    _validate_no_folder_cycle(session, folder.id, next_parent_id)
    validate_folder_parent(session, next_parent_id)
    ensure_folder_name_available(session, next_name, next_parent_id, exclude_folder_id=folder.id)

    folder.name = next_name
    folder.parent_folder_id = next_parent_id
    session.commit()
    session.refresh(folder)
    return folder


def _collect_folder_storage_paths(folder: Folder) -> list[str]:
    paths = [stored_file.storage_path for stored_file in folder.files]
    for child in folder.children:
        paths.extend(_collect_folder_storage_paths(child))
    return paths


def delete_folder(session: Session, folder_id: int) -> None:
    folder = get_folder_or_404(session, folder_id)
    storage_paths = _collect_folder_storage_paths(folder)
    session.delete(folder)
    session.commit()
    _delete_storage_paths(storage_paths)


def _file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_supported_file(filename: str) -> str:
    extension = _file_extension(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type.")
    return extension


def _storage_root() -> Path:
    root = get_settings().storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_storage_path(stored_file: StoredFile) -> Path:
    root = _storage_root().resolve()
    candidate = (root / stored_file.storage_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=500, detail="Stored file location is invalid.")
    return candidate


async def upload_one_file(
    session: Session,
    upload: UploadFile,
    folder_id: int | None,
) -> StoredFile:
    original_filename = validate_display_name(upload.filename or "", "Filename")
    extension = validate_supported_file(original_filename)
    validate_folder_parent(session, folder_id)
    ensure_file_name_available(session, original_filename, folder_id)

    stored_filename = f"{uuid4().hex}{extension}"
    relative_storage_path = stored_filename
    target_path = _storage_root() / stored_filename
    max_upload_bytes = get_settings().max_upload_bytes
    total_size = 0

    try:
        with target_path.open("wb") as output:
            while chunk := await upload.read(CHUNK_SIZE):
                total_size += len(chunk)
                if total_size > max_upload_bytes:
                    raise HTTPException(status_code=413, detail="File exceeds the configured upload size limit.")
                output.write(chunk)
    except HTTPException:
        target_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        logger.exception("File upload failed during storage write.")
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="File could not be stored.") from exc

    stored_file = StoredFile(
        folder_id=folder_id,
        original_filename=original_filename,
        display_name=original_filename,
        stored_filename=stored_filename,
        storage_path=relative_storage_path,
        mime_type=upload.content_type or "application/octet-stream",
        file_size=total_size,
    )
    session.add(stored_file)
    try:
        session.commit()
    except Exception:
        session.rollback()
        target_path.unlink(missing_ok=True)
        logger.exception("File upload failed during database write.")
        raise HTTPException(status_code=500, detail="File could not be saved.") from None

    session.refresh(stored_file)
    return stored_file


def update_file(
    session: Session,
    file_id: int,
    display_name: str | object = _UNSET,
    folder_id: int | None | object = _UNSET,
) -> StoredFile:
    stored_file = get_file_or_404(session, file_id)
    if display_name is not _UNSET and display_name is None:
        raise HTTPException(status_code=400, detail="Filename is required.")
    next_display_name = (
        stored_file.display_name
        if display_name is _UNSET
        else validate_display_name(str(display_name), "Filename")
    )
    next_folder_id = stored_file.folder_id if folder_id is _UNSET else folder_id

    if next_folder_id is not None and not isinstance(next_folder_id, int):
        raise HTTPException(status_code=400, detail="Invalid folder.")
    validate_folder_parent(session, next_folder_id)
    ensure_file_name_available(session, next_display_name, next_folder_id, exclude_file_id=stored_file.id)

    stored_file.display_name = next_display_name
    stored_file.folder_id = next_folder_id
    session.commit()
    session.refresh(stored_file)
    return stored_file


def delete_file(session: Session, file_id: int) -> None:
    stored_file = get_file_or_404(session, file_id)
    storage_path = stored_file.storage_path
    session.delete(stored_file)
    session.commit()
    _delete_storage_paths([storage_path])


def mark_source_file_removed_by_retention(
    session: Session,
    stored_file: StoredFile,
    *,
    reason: str = SOURCE_FILE_REMOVAL_RETENTION,
) -> None:
    if not stored_file.source_file_available:
        return
    storage_path = stored_file.storage_path
    _delete_storage_paths([storage_path])
    stored_file.source_file_available = False
    stored_file.source_file_removed_at = datetime.now(UTC)
    stored_file.source_file_removal_reason = reason


def _delete_storage_paths(storage_paths: list[str]) -> None:
    root = _storage_root().resolve()
    for storage_path in storage_paths:
        candidate = (root / storage_path).resolve()
        if candidate != root and root in candidate.parents:
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                logger.exception("Stored file cleanup failed.")


def ensure_preview_supported(stored_file: StoredFile) -> None:
    if stored_file.mime_type in PREVIEW_MIME_TYPES:
        return
    extension = _file_extension(stored_file.display_name)
    if extension in {".pdf", ".jpg", ".jpeg", ".png"}:
        return
    raise HTTPException(status_code=415, detail="Preview is not supported for this file type.")


def ensure_source_file_available(stored_file: StoredFile) -> None:
    if stored_file.source_file_available:
        return
    raise HTTPException(status_code=410, detail="Original source file no longer stored.")


def _file_item(stored_file: StoredFile) -> FileTreeItem:
    return FileTreeItem.from_orm(stored_file)


def _folder_node(folder: Folder, folders_by_parent: dict[int | None, list[Folder]], files_by_folder: dict[int | None, list[StoredFile]], search: str) -> FolderTreeNode | None:
    folder_matches = search in folder.name.lower() if search else True
    child_force = bool(search and folder_matches)
    child_nodes: list[FolderTreeNode] = []
    file_items: list[FileTreeItem] = []

    for child in folders_by_parent.get(folder.id, []):
        node = _folder_node(child, folders_by_parent, files_by_folder, "" if child_force else search)
        if node is not None:
            child_nodes.append(node)

    for stored_file in files_by_folder.get(folder.id, []):
        if child_force or not search or search in stored_file.display_name.lower():
            file_items.append(_file_item(stored_file))

    if not search or folder_matches or child_nodes or file_items:
        return FolderTreeNode.from_orm(folder).copy(update={"folders": child_nodes, "files": file_items})

    return None


def build_tree(
    session: Session,
    sort_by: str = "name",
    sort_direction: str = "asc",
    search: str = "",
) -> tuple[list[FolderTreeNode], list[FileTreeItem]]:
    folders = list(session.execute(select(Folder)).scalars().all())
    files = list(
        session.execute(
            select(StoredFile).where(StoredFile.source_file_available.is_(True))
        ).scalars().all()
    )
    descending = sort_direction == "desc"
    safe_sort = sort_by if sort_by in {"name", "created_at", "updated_at", "file_size"} else "name"
    search_text = search.strip().lower()

    folders_by_parent: dict[int | None, list[Folder]] = defaultdict(list)
    files_by_folder: dict[int | None, list[StoredFile]] = defaultdict(list)

    for folder in folders:
        folders_by_parent[folder.parent_folder_id].append(folder)
    for stored_file in files:
        files_by_folder[stored_file.folder_id].append(stored_file)

    def folder_key(folder: Folder):
        if safe_sort == "created_at":
            return folder.created_at
        if safe_sort == "updated_at":
            return folder.updated_at
        return folder.name.lower()

    def file_key(stored_file: StoredFile):
        if safe_sort == "created_at":
            return stored_file.created_at
        if safe_sort == "updated_at":
            return stored_file.updated_at
        if safe_sort == "file_size":
            return stored_file.file_size
        return stored_file.display_name.lower()

    for sibling_folders in folders_by_parent.values():
        sibling_folders.sort(key=folder_key, reverse=descending)
    for sibling_files in files_by_folder.values():
        sibling_files.sort(key=file_key, reverse=descending)

    root_folders = [
        node
        for folder in folders_by_parent.get(None, [])
        if (node := _folder_node(folder, folders_by_parent, files_by_folder, search_text)) is not None
    ]
    root_files = [
        _file_item(stored_file)
        for stored_file in files_by_folder.get(None, [])
        if not search_text or search_text in stored_file.display_name.lower()
    ]
    return root_folders, root_files


def _folder_chain(folder_id: int | None, folders_by_id: dict[int, Folder]) -> list[Folder]:
    if folder_id is None:
        return []

    chain: list[Folder] = []
    current = folders_by_id.get(folder_id)
    seen: set[int] = set()

    while current is not None and current.id not in seen:
        seen.add(current.id)
        chain.append(current)
        current = folders_by_id.get(current.parent_folder_id) if current.parent_folder_id is not None else None

    return list(reversed(chain))


def _parent_path(chain: list[Folder]) -> list[str]:
    return ["My Files", *[folder.name for folder in chain]]


def search_items(session: Session, query: str, limit: int = 40) -> list[SearchResult]:
    search_text = query.strip().lower()
    if not search_text:
        return []

    folders = list(session.execute(select(Folder)).scalars().all())
    files = list(
        session.execute(
            select(StoredFile).where(StoredFile.source_file_available.is_(True))
        ).scalars().all()
    )
    folders_by_id = {folder.id: folder for folder in folders}
    results: list[SearchResult] = []

    for stored_file in files:
        if search_text not in stored_file.display_name.lower():
            continue
        parent_chain = _folder_chain(stored_file.folder_id, folders_by_id)
        results.append(
            SearchResult(
                id=stored_file.id,
                type="file",
                name=stored_file.display_name,
                parent_path=_parent_path(parent_chain),
                expand_folder_ids=[folder.id for folder in parent_chain],
                folder_id=stored_file.folder_id,
                mime_type=stored_file.mime_type,
                file_size=stored_file.file_size,
                updated_at=stored_file.updated_at,
            )
        )

    for folder in folders:
        if search_text not in folder.name.lower():
            continue
        parent_chain = _folder_chain(folder.parent_folder_id, folders_by_id)
        results.append(
            SearchResult(
                id=folder.id,
                type="folder",
                name=folder.name,
                parent_path=_parent_path(parent_chain),
                expand_folder_ids=[*[ancestor.id for ancestor in parent_chain], folder.id],
                parent_folder_id=folder.parent_folder_id,
                updated_at=folder.updated_at,
            )
        )

    return sorted(
        results,
        key=lambda result: (result.type != "folder", result.name.lower(), " / ".join(result.parent_path).lower()),
    )[:limit]
