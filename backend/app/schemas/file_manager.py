from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    parent_folder_id: int | None = None


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_folder_id: int | None = None


class FileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    folder_id: int | None = None


class FolderResponse(BaseModel):
    id: int
    parent_folder_id: int | None
    name: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class FileResponse(BaseModel):
    id: int
    folder_id: int | None
    original_filename: str
    display_name: str
    stored_filename: str
    mime_type: str
    file_size: int
    source_file_available: bool
    source_file_removed_at: datetime | None
    source_file_removal_reason: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class FileTreeItem(FileResponse):
    type: str = "file"


class FolderTreeNode(FolderResponse):
    type: str = "folder"
    folders: list[FolderTreeNode] = Field(default_factory=list)
    files: list[FileTreeItem] = Field(default_factory=list)


class FileManagerTree(BaseModel):
    type: str = "root"
    name: str = "My Files"
    folders: list[FolderTreeNode] = Field(default_factory=list)
    files: list[FileTreeItem] = Field(default_factory=list)


class UploadSuccess(BaseModel):
    filename: str
    file: FileResponse


class UploadFailure(BaseModel):
    filename: str
    error: str


class UploadBatchResponse(BaseModel):
    uploaded: list[UploadSuccess]
    failed: list[UploadFailure]


class SearchResult(BaseModel):
    id: int
    type: Literal["file", "folder"]
    name: str
    parent_path: list[str]
    expand_folder_ids: list[int]
    parent_folder_id: int | None = None
    folder_id: int | None = None
    mime_type: str | None = None
    file_size: int | None = None
    updated_at: datetime


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult] = Field(default_factory=list)


FolderTreeNode.update_forward_refs()
