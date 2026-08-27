# Personal Financial File Manager

Personal Financial File Manager is a single-user personal website for organizing personal financial files, previewing stored documents, and later analyzing bank and credit-card statements.

Current Development Phase:
Phase 10 - Packaging, Backup, Updates, and Maintenance

This application is intentionally single-user and does not include login/authentication.

## Architecture

- React, TypeScript, and Vite frontend in `frontend/`
- FastAPI backend in `backend/`
- SQLite database configured through SQLAlchemy
- Alembic database migrations
- Private local file storage under `storage/files/`
- Saved transaction analysis, categorization, selection, review, and reporting
- Local Excel generation with the bundled Python runtime

## Packaged Windows Application

The production build is a single windowless Windows executable. It serves prebuilt frontend assets from FastAPI at a local-only `127.0.0.1` URL, opens the browser automatically, prevents duplicate instances, chooses a safe alternate port when required, and performs startup migrations before serving the UI. The packaged application does not use Vite, reload mode, a separately installed Python runtime, or Node.js.

Writable production state is kept under `%LOCALAPPDATA%\PersonalFinanceManager` and is never installed beside replaceable application files. See [the user guide](docs/USER_GUIDE.md) and [release guide](docs/RELEASE_GUIDE.md).

Build release artifacts from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-release.ps1
```

## Setup

Create a local environment file:

```powershell
Copy-Item .env.example .env
```

Install backend dependencies:

```powershell
cd backend
python -m venv ..\.venv
..\.venv\bin\python.exe -m pip install --upgrade pip
..\.venv\bin\python.exe -m pip install -e ".[dev]"
```

Install frontend dependencies:

```powershell
cd frontend
npm install
```

## Environment Configuration

Copy `.env.example` to `.env` and edit values as needed.

Key values:

- `FRONTEND_URL` controls the allowed local CORS origins for the backend as a comma-separated list.
- `DATABASE_URL` may be left blank to use the default local SQLite database at `data/app.db`.
- `STORAGE_DIR` may be left blank to use private local storage at `storage/files/`.
- `MAX_UPLOAD_BYTES` controls the per-file upload size limit. The default is 25 MB.
- `VITE_API_URL` controls the backend API base URL used by the frontend. The frontend defaults to `http://127.0.0.1:8000`; create `frontend/.env` from `frontend/.env.example` only if you need to override it.
- `SUMMARY_EXPORT_NODE` may point to the local Node.js executable used for Excel exports; when blank, the backend uses `node` from `PATH`.
- `SUMMARY_EXPORT_NODE_MODULES` may point to the local `node_modules` directory containing `@oai/artifact-tool`, which is required for Excel export generation.

Do not commit `.env`, database files, uploaded statements, or other personal financial data.

## Database Migrations

From `backend/`:

```powershell
..\.venv\bin\alembic.exe upgrade head
..\.venv\bin\alembic.exe current
```

Phase 1 added the temporary `infrastructure_checks` table.

Phase 2 adds:

- `folders`
- `files`

Folders use `parent_folder_id` as a nullable self-reference, which supports arbitrary nesting. Files reference folders through `folder_id`, which may be null for root-level files.

Phase 3 adds:

- `statements`

Each statement detection record is linked one-to-one with a file through `file_id`, so re-analysis updates the existing metadata instead of creating duplicates.

## Storage Architecture

Uploaded files are stored privately by the backend in `storage/files/`.

The original uploaded filename is preserved in the database as `original_filename` and `display_name`, but the physical file uses a generated unique filename such as:

```text
7d7df8d2c8f44b81a4f7db8b6f9183c9.pdf
```

The frontend never receives the raw storage path. Files are downloaded or previewed through backend endpoints.

Duplicate display names are prevented within the same folder to keep the personal file tree clear. The same display name may be used in different folders.

Exact duplicate file content is also rejected within the same folder, even when the duplicate is renamed. This prevents an accidentally re-imported statement from producing a second set of transactions while preserving the file manager's existing folder boundary.

Folder deletion uses database cascades for child records, then removes the corresponding private stored files. File deletion removes the database record and then deletes the physical file.

## Running the Backend

From `backend/`:

```powershell
..\.venv\bin\uvicorn.exe app.main:app --reload --host 127.0.0.1 --port 8000
```

Useful checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/health/db
Invoke-RestMethod http://127.0.0.1:8000/api/file-manager/tree
```

## Running the Frontend

From `frontend/`:

```powershell
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`.

## File Manager API

Core endpoints:

```text
GET    /api/file-manager/tree
GET    /api/folders
POST   /api/folders
PATCH  /api/folders/{id}
DELETE /api/folders/{id}
GET    /api/files
POST   /api/files
PATCH  /api/files/{id}
DELETE /api/files/{id}
GET    /api/files/{id}/download
GET    /api/files/{id}/preview
GET    /api/files/{id}/statement
POST   /api/files/{id}/detect-statement
GET    /api/summary
GET    /api/summary/export.xlsx
```

The tree endpoint supports:

```text
search=
sort_by=name|created_at|updated_at|file_size
sort_direction=asc|desc
```

Statement detection is manual in Phase 3. Select a PDF in the file manager and use Analyze File or Re-analyze to store document-level metadata such as institution, document type, account type, last four, statement period, confidence, and status. Full PDF text, full account numbers, balances, and transaction rows are not stored.

Supported deterministic detection targets:

- Chase
- Capital One
- American Express
- PayPal
- TJX / TJ Maxx
- Amazon-branded financial products
- Other / Unknown

## Tests

Backend tests and syntax check:

```powershell
cd backend
..\.venv\bin\pytest.exe
..\.venv\bin\python.exe -m compileall app tests
```

Frontend checks:

```powershell
cd frontend
npm run lint
npm run typecheck
npm run build
```

## Developer Convenience

On Windows, after setup:

```powershell
.\scripts\dev.ps1
```

On macOS/Linux, after setup:

```bash
./scripts/dev.sh
```

## Expense Summary

The Summary page combines authoritative saved transaction records across analyzed statements. It supports tax-year and inclusive custom-date reporting, the approved fixed category order, Needs Review navigation, source-row traceability, retained historical transactions, and a minimal black-and-white Excel Summary export. The workbook contains no transaction-detail worksheet. Only selected, eligible transactions with valid saved categories contribute to totals; the reporting layer never categorizes transactions or resets selections.
