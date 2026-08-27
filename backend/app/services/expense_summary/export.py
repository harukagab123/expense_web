from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from fastapi import HTTPException

from app.schemas.summary import ExpenseSummaryResponse

PROJECT_ROOT = Path(__file__).resolve().parents[4]
BUILDER_PATH = PROJECT_ROOT / "backend" / "scripts" / "summary_workbook.mjs"
CODEX_ARTIFACT_NODE_MODULES = (
    Path.home()
    / ".cache"
    / "codex-runtimes"
    / "codex-primary-runtime"
    / "dependencies"
    / "node"
    / "node_modules"
)


@dataclass(frozen=True)
class ExportedWorkbook:
    content: bytes
    filename: str


def _node_modules_path() -> Path:
    configured = os.getenv("SUMMARY_EXPORT_NODE_MODULES", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(CODEX_ARTIFACT_NODE_MODULES)
    for candidate in candidates:
        if (candidate / "@oai" / "artifact-tool").is_dir():
            return candidate.resolve()
    raise HTTPException(
        status_code=503,
        detail="Excel export runtime is unavailable. Configure SUMMARY_EXPORT_NODE_MODULES.",
    )


def _node_executable() -> str:
    configured = os.getenv("SUMMARY_EXPORT_NODE", "").strip()
    executable = configured or shutil.which("node")
    if not executable:
        raise HTTPException(status_code=503, detail="Excel export requires a local Node.js runtime.")
    return executable


def _link_node_modules(target: Path, source: Path) -> None:
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(target), str(source)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise OSError(completed.stderr or completed.stdout or "Could not create export runtime junction.")


def _safe_filename(summary: ExpenseSummaryResponse) -> str:
    if summary.period.mode == "TAX_YEAR" and summary.period.tax_year:
        suffix = str(summary.period.tax_year)
    else:
        suffix = f"{summary.period.start_date.isoformat()}-to-{summary.period.end_date.isoformat()}"
    return f"expense-summary-{suffix}.xlsx"


def export_expense_summary(summary: ExpenseSummaryResponse) -> ExportedWorkbook:
    node_modules = _node_modules_path()
    node = _node_executable()
    with tempfile.TemporaryDirectory(prefix="expense-summary-") as temporary_directory:
        workdir = Path(temporary_directory)
        _link_node_modules(workdir / "node_modules", node_modules)
        script_path = workdir / BUILDER_PATH.name
        shutil.copy2(BUILDER_PATH, script_path)
        input_path = workdir / "summary.json"
        output_path = workdir / "summary.xlsx"
        input_path.write_text(summary.json(), encoding="utf-8")
        completed = subprocess.run(
            [node, str(script_path), "build", str(input_path), str(output_path)],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0 or not output_path.is_file():
            raise HTTPException(status_code=500, detail="Excel export could not be generated.")
        return ExportedWorkbook(content=output_path.read_bytes(), filename=_safe_filename(summary))


def inspect_expense_summary_workbook(
    content: bytes,
    *,
    summary_preview_path: Path | None = None,
    detail_preview_path: Path | None = None,
) -> dict:
    node_modules = _node_modules_path()
    node = _node_executable()
    with tempfile.TemporaryDirectory(prefix="expense-summary-inspect-") as temporary_directory:
        workdir = Path(temporary_directory)
        _link_node_modules(workdir / "node_modules", node_modules)
        script_path = workdir / BUILDER_PATH.name
        shutil.copy2(BUILDER_PATH, script_path)
        input_path = workdir / "summary.xlsx"
        input_path.write_bytes(content)
        command = [node, str(script_path), "inspect", str(input_path)]
        if summary_preview_path is not None:
            summary_preview_path.parent.mkdir(parents=True, exist_ok=True)
            command.append(str(summary_preview_path))
            if detail_preview_path is not None:
                detail_preview_path.parent.mkdir(parents=True, exist_ok=True)
                command.append(str(detail_preview_path))
        completed = subprocess.run(
            command,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or completed.stdout or "Workbook validation failed.")
        return json.loads(completed.stdout)
