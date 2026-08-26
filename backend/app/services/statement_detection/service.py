from __future__ import annotations

from datetime import UTC, datetime
import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import StoredFile
from app.models.statement import Statement
from app.schemas.statement import StatementUpdate
from app.services.file_manager import ensure_source_file_available, get_file_or_404, resolve_storage_path
from app.services.statement_detection.base import (
    ACCOUNT_UNKNOWN,
    DOCUMENT_UNKNOWN,
    INSTITUTION_UNKNOWN,
    STATUS_ANALYZING,
    STATUS_FAILED,
    DetectionResult,
)
from app.services.statement_detection.detector import detect_statement_text
from app.services.statement_detection.pdf_text import PdfTextExtractionError, extract_pdf_text

logger = logging.getLogger(__name__)

SOURCE_DETECTED = "DETECTED"
SOURCE_USER_EDITED = "USER_EDITED"

EDITABLE_FIELDS = (
    "document_type",
    "institution",
    "product_name",
    "account_type",
    "account_last_four",
    "statement_start_date",
    "statement_end_date",
)


def get_statement_for_file(session: Session, file_id: int) -> Statement | None:
    get_file_or_404(session, file_id)
    return session.execute(select(Statement).where(Statement.file_id == file_id)).scalar_one_or_none()


def detect_statement_for_file(session: Session, file_id: int) -> Statement:
    stored_file = get_file_or_404(session, file_id)
    ensure_source_file_available(stored_file)
    _ensure_pdf_supported(stored_file)
    file_path = resolve_storage_path(stored_file)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Stored file is missing.")

    statement = _get_or_create_statement(session, stored_file.id)
    _mark_analyzing(session, statement)

    try:
        text = extract_pdf_text(file_path)
        result = detect_statement_text(text, filename=stored_file.display_name)
    except PdfTextExtractionError:
        logger.exception("Statement detection failed for file_id=%s", stored_file.id)
        _apply_failed_result(statement, "The PDF could not be read.")
    except Exception:
        logger.exception("Statement detection failed for file_id=%s", stored_file.id)
        _apply_failed_result(statement, "Unable to analyze this file.")
    else:
        _apply_detection_result(statement, result)

    statement.detected_at = datetime.now(UTC)
    if statement.original_detected_at is None:
        _store_original_detection(statement, statement.detected_at)
    session.commit()
    session.refresh(statement)
    return statement


def update_statement_for_file(session: Session, file_id: int, payload: StatementUpdate) -> Statement:
    get_file_or_404(session, file_id)
    statement = session.execute(select(Statement).where(Statement.file_id == file_id)).scalar_one_or_none()
    if statement is None:
        raise HTTPException(status_code=404, detail="Analyze the file before editing statement details.")

    updates = {field: getattr(payload, field) for field in EDITABLE_FIELDS if field in payload.__fields_set__}
    if not updates:
        return statement

    next_start_date = updates.get("statement_start_date", statement.statement_start_date)
    next_end_date = updates.get("statement_end_date", statement.statement_end_date)
    if next_start_date is not None and next_end_date is not None and next_start_date > next_end_date:
        raise HTTPException(status_code=422, detail="Statement start date must be on or before statement end date.")

    for field, value in updates.items():
        setattr(statement, field, value)

    statement.user_corrected = True
    statement.metadata_source = SOURCE_USER_EDITED
    statement.manual_updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(statement)
    return statement


def _ensure_pdf_supported(stored_file: StoredFile) -> None:
    extension = Path(stored_file.display_name).suffix.lower()
    if stored_file.mime_type == "application/pdf" or extension == ".pdf":
        return
    raise HTTPException(status_code=415, detail="Statement detection is available for PDF files only.")


def _get_or_create_statement(session: Session, file_id: int) -> Statement:
    statement = session.execute(select(Statement).where(Statement.file_id == file_id)).scalar_one_or_none()
    if statement is not None:
        return statement

    statement = Statement(
        file_id=file_id,
        document_type=DOCUMENT_UNKNOWN,
        institution=INSTITUTION_UNKNOWN,
        account_type="UNKNOWN",
        detection_confidence=0.0,
        detection_status=STATUS_ANALYZING,
        metadata_source=SOURCE_DETECTED,
        user_corrected=False,
    )
    session.add(statement)
    session.commit()
    session.refresh(statement)
    return statement


def _mark_analyzing(session: Session, statement: Statement) -> None:
    statement.detection_status = STATUS_ANALYZING
    statement.detection_reason = None
    session.commit()
    session.refresh(statement)


def _apply_failed_result(statement: Statement, reason: str) -> None:
    result = DetectionResult(
        document_type=DOCUMENT_UNKNOWN,
        institution=INSTITUTION_UNKNOWN,
        account_type=ACCOUNT_UNKNOWN,
        confidence=0.0,
        status=STATUS_FAILED,
        reason=reason,
    )
    _apply_detection_result(statement, result)


def _apply_detection_result(statement: Statement, result: DetectionResult) -> None:
    _store_latest_detection(statement, result)
    if not statement.user_corrected:
        _store_current_metadata(statement, result)
        statement.metadata_source = SOURCE_DETECTED

    statement.detection_confidence = result.confidence
    statement.detection_status = result.status
    statement.detection_reason = result.reason


def _store_current_metadata(statement: Statement, result: DetectionResult) -> None:
    statement.document_type = result.document_type
    statement.institution = result.institution
    statement.product_name = result.product_name
    statement.account_type = result.account_type
    statement.account_last_four = result.account_last_four
    statement.statement_start_date = result.statement_start_date
    statement.statement_end_date = result.statement_end_date


def _store_latest_detection(statement: Statement, result: DetectionResult) -> None:
    statement.detected_document_type = result.document_type
    statement.detected_institution = result.institution
    statement.detected_product_name = result.product_name
    statement.detected_account_type = result.account_type
    statement.detected_account_last_four = result.account_last_four
    statement.detected_statement_start_date = result.statement_start_date
    statement.detected_statement_end_date = result.statement_end_date


def _store_original_detection(statement: Statement, detected_at: datetime) -> None:
    statement.original_document_type = statement.detected_document_type
    statement.original_institution = statement.detected_institution
    statement.original_product_name = statement.detected_product_name
    statement.original_account_type = statement.detected_account_type
    statement.original_account_last_four = statement.detected_account_last_four
    statement.original_statement_start_date = statement.detected_statement_start_date
    statement.original_statement_end_date = statement.detected_statement_end_date
    statement.original_detected_at = detected_at
