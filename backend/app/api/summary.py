from __future__ import annotations

from datetime import date
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.summary import ExpenseSummaryResponse
from app.services.expense_summary.export import export_expense_summary
from app.services.expense_summary.service import build_expense_summary

router = APIRouter(prefix="/summary", tags=["summary"])


@router.get("", response_model=ExpenseSummaryResponse)
def read_expense_summary(
    tax_year: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
) -> ExpenseSummaryResponse:
    return build_expense_summary(
        db,
        tax_year=tax_year,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/export.xlsx")
def export_expense_summary_workbook(
    tax_year: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    summary = build_expense_summary(
        db,
        tax_year=tax_year,
        start_date=start_date,
        end_date=end_date,
    )
    workbook = export_expense_summary(summary)
    encoded_filename = quote(workbook.filename)
    return StreamingResponse(
        BytesIO(workbook.content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
    )
