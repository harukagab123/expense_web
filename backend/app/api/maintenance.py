from __future__ import annotations

import os
from pathlib import Path
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.services.maintenance import BackupError, create_backup, create_diagnostic_bundle, maintenance_status, restore_backup
from app.services.maintenance.migrations import MigrationError, migrate_database


router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("/status")
def read_maintenance_status(integrity: bool = False) -> dict[str, object]:
    return maintenance_status(integrity=integrity)


@router.post("/backups")
def create_manual_backup() -> FileResponse:
    try:
        path = create_backup(kind="manual")
    except BackupError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/restore")
async def restore_uploaded_backup(backup: UploadFile = File(...), confirm: bool = Form(...)) -> dict[str, object]:
    if not confirm:
        raise HTTPException(status_code=400, detail="Explicit restore confirmation is required.")
    if not backup.filename or not backup.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Select a Personal Finance Manager backup ZIP.")
    with tempfile.TemporaryDirectory(prefix="pfm-uploaded-restore-") as temporary:
        upload_path = Path(temporary) / "restore.zip"
        size = 0
        with upload_path.open("wb") as destination:
            while chunk := await backup.read(1024 * 1024):
                size += len(chunk)
                if size > 2 * 1024 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Backup is too large to restore.")
                destination.write(chunk)
        try:
            safety_backup, manifest = restore_backup(upload_path)
            migrate_database()
        except (BackupError, MigrationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "restored",
        "safety_backup_created": True,
        "safety_backup_name": safety_backup.name,
        "restored_app_version": manifest.get("app_version"),
    }


@router.post("/diagnostics")
def export_diagnostics() -> FileResponse:
    path = create_diagnostic_bundle()
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/open-backup-folder")
def open_backup_folder() -> dict[str, str]:
    settings = get_settings()
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        raise HTTPException(status_code=501, detail="Open the backup directory shown under Advanced.")
    os.startfile(settings.backups_dir)  # type: ignore[attr-defined]
    return {"status": "opened"}
