# Release Guide

The authoritative version is `APP_VERSION` in `backend/app/version.py`. Use semantic versions.

## Release workflow

1. Update `APP_VERSION` and review Alembic migrations.
2. Confirm `.env`, databases, storage, backups, logs, diagnostics, exports, and credentials are not staged.
3. From the repository root, run `powershell -ExecutionPolicy Bypass -File scripts/build-release.ps1`.
4. The script installs locked frontend dependencies, runs frontend lint/typecheck/build, runs backend tests, and creates the windowless PyInstaller executable.
5. When Inno Setup 6 is installed and `ISCC.exe` is on `PATH`, the script also creates `PersonalFinanceManager-<version>-Setup.exe`.
6. Test the produced package with a temporary `PFM_DATA_DIR`: first run, close/reopen, backup/restore, update backup, and persistence.
7. Scan the artifact for `.env`, tokens, keys, passwords, developer paths, databases, statements, logs, backups, diagnostics, and exports.
8. Distribute the signed installer through a private channel. Never add private-repository credentials to the application.

The installer uses per-user application files and preserves `%LOCALAPPDATA%\PersonalFinanceManager` during uninstall. When updating an existing install, it runs `PersonalFinanceManager.exe --prepare-update <version>` and aborts if a validated safety backup cannot be created. After that backup succeeds, setup closes the windowless application before replacing files. Uninstall uses the same named-process handoff so locked program files are removed without deleting user data.

The portable release build recognizes the repository `data/app.db` and `storage/files` layout when run from `outputs/release`. For a different legacy location, set `PFM_LEGACY_ROOT` only for the first launch. The verified copy is placed in the per-user directory; the legacy originals are never deleted.

## Rollback

Application installation is handled by the standard installer. Database migrations are handled at launcher startup. Before a pending migration, the launcher creates and validates an automatic backup. If migration fails, it restores the previous database and stops startup. Keep the previous signed installer plus the matching pre-update backup for a complete application-version rollback.
