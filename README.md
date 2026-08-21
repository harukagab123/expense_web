# Personal Financial File Manager

Personal Financial File Manager is a single-user personal website for organizing financial files, analyzing bank and credit-card statements, selecting and categorizing transactions, and producing expense summaries.

Current Development Phase:
Phase 1 - Project Foundation

This application is intentionally single-user and does not include login/authentication.

## Architecture

- React, TypeScript, and Vite frontend in `frontend/`
- FastAPI backend in `backend/`
- SQLite database configured through SQLAlchemy
- Alembic database migrations
- Local generated data stored outside Git-tracked files

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
- `VITE_API_URL` controls the backend API base URL used by the frontend. The frontend defaults to `http://127.0.0.1:8000`; create `frontend/.env` from `frontend/.env.example` only if you need to override it.

Do not commit `.env`, database files, uploaded statements, or other personal financial data.

## Database Migrations

From `backend/`:

```powershell
..\.venv\bin\alembic.exe upgrade head
..\.venv\bin\alembic.exe current
```

Phase 1 includes one temporary infrastructure table, `infrastructure_checks`, used only to prove database write/read behavior.

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
```

## Running the Frontend

From `frontend/`:

```powershell
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`.

## Tests

Backend tests and lint:

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

## Current Limitations

Phase 1 does not yet contain:

- folder management
- file uploads
- bank statement processing
- OCR
- transaction extraction
- categorization
- expense selection
- reports
- exports

The next development phase is:

PHASE 2 - File and Folder Management
