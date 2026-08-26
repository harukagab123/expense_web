from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from app.models.statement import Statement
from app.models.transaction import Transaction, TransactionExtraction
from app.schemas.analysis import (
    AnalysisStepResponse,
    RetentionRemovedFileResponse,
    RetentionSummaryResponse,
    StatementAnalysisResponse,
)
from app.schemas.statement import StatementResponse
from app.schemas.transaction import TransactionExtractionResponse, TransactionResponse
from app.services.source_retention import RetentionResult, apply_retention_for_statement
from app.services.statement_detection.base import STATUS_FAILED as DETECTION_FAILED
from app.services.statement_detection.service import detect_statement_for_file
from app.services.transaction_categorization.service import categorize_transactions_for_statement
from app.services.transaction_extraction.base import STATUS_FAILED as EXTRACTION_FAILED
from app.services.transaction_extraction.base import STATUS_UNSUPPORTED as EXTRACTION_UNSUPPORTED
from app.services.transaction_extraction.service import extract_transactions_for_statement
from app.services.transaction_normalization.service import normalize_transactions_for_statement
from app.services.transaction_type_detection.service import classify_transaction_types_for_statement


@dataclass
class _AnalysisState:
    key: str
    label: str
    status: str = "PENDING"
    message: str | None = None


STEP_DETECTION = "statement_detection"
STEP_EXTRACTION = "transaction_extraction"
STEP_NORMALIZATION = "transaction_normalization"
STEP_TYPE_CLASSIFICATION = "transaction_type_classification"
STEP_CATEGORIZATION = "transaction_categorization"
STEP_NOTIFICATION_REFRESH = "review_notification_refresh"
STEP_RETENTION = "source_file_retention"


def analyze_statement_file(session: Session, file_id: int) -> StatementAnalysisResponse:
    steps = [
        _AnalysisState(STEP_DETECTION, "Statement detection"),
        _AnalysisState(STEP_EXTRACTION, "Transaction extraction"),
        _AnalysisState(STEP_NORMALIZATION, "Normalize transaction names"),
        _AnalysisState(STEP_TYPE_CLASSIFICATION, "Classify transaction types"),
        _AnalysisState(STEP_CATEGORIZATION, "Categorize eligible transactions"),
        _AnalysisState(STEP_NOTIFICATION_REFRESH, "Refresh review notifications"),
        _AnalysisState(STEP_RETENTION, "Apply source file retention"),
    ]

    statement: Statement | None = None
    extraction: TransactionExtraction | None = None
    transactions: list[Transaction] = []
    retention = RetentionResult()

    _start(steps, STEP_DETECTION)
    statement = detect_statement_for_file(session, file_id)
    if statement.detection_status == DETECTION_FAILED:
        _fail(steps, STEP_DETECTION, statement.detection_reason or "Statement detection failed.")
        return _response("FAILED", STEP_DETECTION, statement, extraction, transactions, steps, retention)
    _complete(steps, STEP_DETECTION, "Statement metadata updated.")

    _start(steps, STEP_EXTRACTION)
    extraction, transactions = extract_transactions_for_statement(session, statement.id)
    if extraction.status in {EXTRACTION_FAILED, EXTRACTION_UNSUPPORTED}:
        _fail(steps, STEP_EXTRACTION, extraction.message or "Transaction extraction failed.")
        _skip_after_failure(steps, STEP_EXTRACTION)
        return _response("FAILED", STEP_EXTRACTION, statement, extraction, transactions, steps, retention)
    _complete(steps, STEP_EXTRACTION, f"{len(transactions)} transactions loaded.")

    _start(steps, STEP_NORMALIZATION)
    transactions = normalize_transactions_for_statement(session, statement.id)
    _complete(steps, STEP_NORMALIZATION, "Names normalized.")

    _start(steps, STEP_TYPE_CLASSIFICATION)
    transactions = classify_transaction_types_for_statement(session, statement.id)
    _complete(steps, STEP_TYPE_CLASSIFICATION, "Transaction types classified.")

    _start(steps, STEP_CATEGORIZATION)
    transactions = categorize_transactions_for_statement(session, statement.id)
    _complete(steps, STEP_CATEGORIZATION, "Eligible transactions categorized.")

    _start(steps, STEP_NOTIFICATION_REFRESH)
    _complete(steps, STEP_NOTIFICATION_REFRESH, "Review and notification state refreshed.")

    _start(steps, STEP_RETENTION)
    session.refresh(statement)
    retention = apply_retention_for_statement(session, statement)
    if retention.removed_count:
        _complete(
            steps,
            STEP_RETENTION,
            f"{retention.removed_count} older source file{'' if retention.removed_count == 1 else 's'} removed.",
        )
    else:
        _complete(steps, STEP_RETENTION, "No older source files removed.")

    return _response("COMPLETED", None, statement, extraction, transactions, steps, retention)


def _start(steps: list[_AnalysisState], key: str) -> None:
    _step(steps, key).status = "RUNNING"


def _complete(steps: list[_AnalysisState], key: str, message: str | None = None) -> None:
    step = _step(steps, key)
    step.status = "COMPLETED"
    step.message = message


def _fail(steps: list[_AnalysisState], key: str, message: str | None = None) -> None:
    step = _step(steps, key)
    step.status = "FAILED"
    step.message = message


def _skip_after_failure(steps: list[_AnalysisState], failed_key: str) -> None:
    failed_seen = False
    for step in steps:
        if step.key == failed_key:
            failed_seen = True
            continue
        if failed_seen and step.status == "PENDING":
            step.status = "SKIPPED"


def _step(steps: list[_AnalysisState], key: str) -> _AnalysisState:
    return next(step for step in steps if step.key == key)


def _response(
    status: str,
    failed_step: str | None,
    statement: Statement,
    extraction: TransactionExtraction | None,
    transactions: list[Transaction],
    steps: list[_AnalysisState],
    retention: RetentionResult,
) -> StatementAnalysisResponse:
    return StatementAnalysisResponse(
        status=status,
        failed_step=failed_step,
        statement=StatementResponse.from_orm(statement),
        extraction=TransactionExtractionResponse.from_orm(extraction) if extraction is not None else None,
        transactions=[TransactionResponse.from_orm(transaction) for transaction in transactions],
        steps=[AnalysisStepResponse(**asdict(step)) for step in steps],
        retention=RetentionSummaryResponse(
            institution=retention.institution,
            removed_count=retention.removed_count,
            removed_files=[
                RetentionRemovedFileResponse(**asdict(removed_file))
                for removed_file in retention.removed_files
            ],
        ),
    )
