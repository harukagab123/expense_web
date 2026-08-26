from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.statement import Statement
from app.models.transaction import Transaction, TransactionExtraction
from app.schemas.transaction import TransactionCreate, TransactionUpdate
from app.services.file_manager import ensure_source_file_available, resolve_storage_path
from app.services.statement_detection.base import INSTITUTION_UNKNOWN
from app.services.statement_detection.pdf_text import PdfTextExtractionError, extract_pdf_pages
from app.services.transaction_extraction.base import (
    DIRECTION_UNKNOWN,
    PageText,
    ParserContext,
    SOURCE_EXTRACTED,
    SOURCE_USER_ADDED,
    STATUS_EXTRACTED,
    STATUS_EXTRACTING,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_UNSUPPORTED,
    ExtractedTransaction,
)
from app.services.transaction_extraction.common import normalize_spaces
from app.services.transaction_extraction.registry import get_transaction_parser

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Phase8State:
    include_in_expenses: bool | None
    inclusion_initialized: bool
    inclusion_source: str
    inclusion_updated_at: datetime | None
    review_status: str
    review_source: str
    review_updated_at: datetime | None


def get_statement_or_404(session: Session, statement_id: int) -> Statement:
    statement = session.get(Statement, statement_id)
    if statement is None:
        raise HTTPException(status_code=404, detail="Statement not found.")
    return statement


def list_transactions_for_statement(
    session: Session,
    statement_id: int,
    *,
    include_excluded: bool = False,
) -> tuple[TransactionExtraction | None, list[Transaction]]:
    get_statement_or_404(session, statement_id)
    latest_extraction = _latest_extraction(session, statement_id)
    transactions = _list_transactions(session, statement_id, include_excluded=include_excluded)
    if not include_excluded:
        from app.services.transaction_review.service import initialize_phase8_state_for_transactions

        if initialize_phase8_state_for_transactions(transactions):
            session.commit()
            transactions = _list_transactions(session, statement_id, include_excluded=include_excluded)
    return latest_extraction, transactions


def extract_transactions_for_statement(session: Session, statement_id: int) -> tuple[TransactionExtraction, list[Transaction]]:
    statement = get_statement_or_404(session, statement_id)
    institution = statement.institution
    if institution == INSTITUTION_UNKNOWN:
        extraction = _create_extraction(
            session,
            statement_id=statement.id,
            parser_name="unsupported",
            parser_version="none",
            status=STATUS_UNSUPPORTED,
            message="Please review the statement details before extracting transactions.",
        )
        from app.services.transaction_review.service import initialize_phase8_state_for_statement

        return extraction, initialize_phase8_state_for_statement(session, statement.id)

    parser = get_transaction_parser(institution)
    if parser is None:
        extraction = _create_extraction(
            session,
            statement_id=statement.id,
            parser_name=f"{institution.lower()}-unsupported",
            parser_version="none",
            status=STATUS_UNSUPPORTED,
            message="Transaction extraction is not yet supported for this statement format.",
        )
        from app.services.transaction_review.service import initialize_phase8_state_for_statement

        return extraction, initialize_phase8_state_for_statement(session, statement.id)

    _ensure_pdf_supported(statement)
    ensure_source_file_available(statement.file)
    file_path = resolve_storage_path(statement.file)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Stored file is missing.")

    extraction = _create_extraction(
        session,
        statement_id=statement.id,
        parser_name=parser.parser_name,
        parser_version=parser.parser_version,
        status=STATUS_EXTRACTING,
        message=None,
    )

    try:
        pdf_pages = [
            PageText(page_number=index + 1, text=text)
            for index, text in enumerate(extract_pdf_pages(file_path))
        ]
        if not pdf_pages:
            extraction.status = STATUS_NEEDS_REVIEW
            extraction.message = "Transaction extraction requires review because this PDF does not contain readable text."
            extraction.completed_at = datetime.now(UTC)
            session.commit()
            session.refresh(extraction)
            from app.services.transaction_review.service import initialize_phase8_state_for_statement

            return extraction, initialize_phase8_state_for_statement(session, statement.id)

        parse_result = parser.parse(
            pdf_pages,
            ParserContext(
                institution=statement.institution,
                product_name=statement.product_name,
                account_type=statement.account_type,
                statement_start_date=statement.statement_start_date,
                statement_end_date=statement.statement_end_date,
            ),
        )
        _replace_unprotected_machine_transactions(session, statement.id, extraction.id, parse_result.transactions)
        active_transactions = _list_transactions(session, statement.id)
        review_count = sum(transaction.needs_review for transaction in active_transactions)
        extraction.transaction_count = len(active_transactions)
        extraction.review_count = review_count
        extraction.status = _status_for_extraction(len(parse_result.transactions), review_count, parse_result.message)
        extraction.message = parse_result.message
        extraction.completed_at = datetime.now(UTC)
    except PdfTextExtractionError:
        logger.exception("Transaction extraction failed while reading PDF for statement_id=%s", statement.id)
        extraction.status = STATUS_FAILED
        extraction.message = "The PDF could not be read."
        extraction.completed_at = datetime.now(UTC)
    except Exception:
        logger.exception("Transaction extraction failed for statement_id=%s", statement.id)
        extraction.status = STATUS_FAILED
        extraction.message = "Unable to extract transactions from this statement."
        extraction.completed_at = datetime.now(UTC)

    session.commit()
    session.refresh(extraction)
    from app.services.transaction_review.service import initialize_phase8_state_for_statement

    return extraction, initialize_phase8_state_for_statement(session, statement.id)


def create_manual_transaction(session: Session, statement_id: int, payload: TransactionCreate) -> Transaction:
    get_statement_or_404(session, statement_id)
    source_order = _next_source_order(session, statement_id)
    transaction = Transaction(
        statement_id=statement_id,
        transaction_date=payload.transaction_date,
        transaction_detail=payload.transaction_detail,
        amount=payload.amount,
        direction=payload.direction,
        source_page=None,
        source_order=source_order,
        extraction_confidence=1.0,
        needs_review=payload.direction == DIRECTION_UNKNOWN,
        user_edited=False,
        user_added=True,
        excluded=False,
        source=SOURCE_USER_ADDED,
    )
    session.add(transaction)
    from app.services.transaction_review.service import initialize_phase8_state

    initialize_phase8_state(transaction)
    _refresh_latest_counts(session, statement_id)
    session.commit()
    session.refresh(transaction)
    return transaction


def update_transaction(session: Session, transaction_id: int, payload: TransactionUpdate) -> Transaction:
    transaction = _get_transaction_or_404(session, transaction_id)
    detail_changed = "transaction_detail" in payload.__fields_set__
    direction_changed = "direction" in payload.__fields_set__
    if "transaction_date" in payload.__fields_set__:
        transaction.transaction_date = payload.transaction_date
    if "transaction_detail" in payload.__fields_set__:
        transaction.transaction_detail = payload.transaction_detail
    if "amount" in payload.__fields_set__:
        transaction.amount = payload.amount
    if "direction" in payload.__fields_set__:
        transaction.direction = payload.direction

    transaction.user_edited = True
    transaction.needs_review = transaction.direction == DIRECTION_UNKNOWN
    if detail_changed:
        from app.services.transaction_normalization.service import reset_machine_normalization

        reset_machine_normalization(transaction)
    if detail_changed or direction_changed:
        from app.services.transaction_type_detection.service import reset_machine_type

        reset_machine_type(transaction)
        if direction_changed:
            from app.services.transaction_categorization.service import reset_category_for_type_change
            from app.services.transaction_type_detection.rules import suggested_include_for_type

            transaction.suggested_include = suggested_include_for_type(transaction.transaction_type, transaction.direction)
            reset_category_for_type_change(transaction)
    if (
        {"transaction_date", "transaction_detail", "amount", "direction"} & payload.__fields_set__
    ):
        from app.services.transaction_review.service import mark_review_needed_after_user_change

        mark_review_needed_after_user_change(transaction)
    _refresh_latest_counts(session, transaction.statement_id)
    session.commit()
    session.refresh(transaction)
    return transaction


def exclude_transaction(session: Session, transaction_id: int) -> Transaction:
    transaction = _get_transaction_or_404(session, transaction_id)
    transaction.excluded = True
    from app.services.transaction_review.service import mark_transaction_record_excluded

    mark_transaction_record_excluded(transaction)
    _refresh_latest_counts(session, transaction.statement_id)
    session.commit()
    session.refresh(transaction)
    return transaction


def _create_extraction(
    session: Session,
    *,
    statement_id: int,
    parser_name: str,
    parser_version: str,
    status: str,
    message: str | None,
) -> TransactionExtraction:
    now = datetime.now(UTC)
    extraction = TransactionExtraction(
        statement_id=statement_id,
        parser_name=parser_name,
        parser_version=parser_version,
        status=status,
        transaction_count=0,
        review_count=0,
        message=message,
        started_at=now,
        completed_at=now if status != STATUS_EXTRACTING else None,
    )
    session.add(extraction)
    session.commit()
    session.refresh(extraction)
    return extraction


def _replace_unprotected_machine_transactions(
    session: Session,
    statement_id: int,
    extraction_id: int,
    extracted_transactions: list[ExtractedTransaction],
) -> None:
    existing_transactions = _list_transactions(session, statement_id, include_excluded=True)
    protected_key_counts = Counter(
        _semantic_key_from_transaction(transaction)
        for transaction in existing_transactions
        if _transaction_is_reprocessing_protected(transaction)
    )
    phase8_state_by_key: dict[tuple[str, str, Decimal, str], list[_Phase8State]] = defaultdict(list)
    for transaction in existing_transactions:
        if transaction.inclusion_initialized or transaction.review_updated_at is not None:
            phase8_state_by_key[_semantic_key_from_transaction(transaction)].append(
                _phase8_state_from_transaction(transaction)
            )
    reusable_transactions_by_key: dict[tuple[str, str, Decimal, str], list[Transaction]] = defaultdict(list)
    for transaction in existing_transactions:
        if not _transaction_is_reprocessing_protected(transaction):
            reusable_transactions_by_key[_semantic_key_from_transaction(transaction)].append(transaction)

    reused_transaction_ids: set[int] = set()

    for extracted in extracted_transactions:
        key = _semantic_key_from_extracted(extracted)
        if protected_key_counts[key] > 0:
            protected_key_counts[key] -= 1
            _pop_phase8_state(phase8_state_by_key, key)
            continue

        reusable_transaction = _pop_reusable_transaction(reusable_transactions_by_key, key)
        if reusable_transaction is not None:
            _pop_phase8_state(phase8_state_by_key, key)
            _apply_extracted_transaction(reusable_transaction, extraction_id, extracted)
            reused_transaction_ids.add(reusable_transaction.id)
            continue

        phase8_state = _pop_phase8_state(phase8_state_by_key, key)
        transaction = _new_extracted_transaction(statement_id, extraction_id, extracted)
        if phase8_state is not None:
            _apply_phase8_state(transaction, phase8_state)
        session.add(transaction)

    for transaction in existing_transactions:
        if not _transaction_is_reprocessing_protected(transaction) and transaction.id not in reused_transaction_ids:
            session.delete(transaction)
    session.flush()


def _transaction_is_reprocessing_protected(transaction: Transaction) -> bool:
    return (
        transaction.user_edited
        or transaction.user_added
        or transaction.excluded
        or transaction.user_edited_normalization
        or transaction.user_edited_type
        or transaction.user_edited_category
        or transaction.review_status == "REVIEWED"
    )


def _phase8_state_from_transaction(transaction: Transaction) -> _Phase8State:
    return _Phase8State(
        include_in_expenses=transaction.include_in_expenses,
        inclusion_initialized=transaction.inclusion_initialized,
        inclusion_source=transaction.inclusion_source,
        inclusion_updated_at=transaction.inclusion_updated_at,
        review_status=transaction.review_status,
        review_source=transaction.review_source,
        review_updated_at=transaction.review_updated_at,
    )


def _pop_phase8_state(
    phase8_state_by_key: dict[tuple[str, str, Decimal, str], list[_Phase8State]],
    key: tuple[str, str, Decimal, str],
) -> _Phase8State | None:
    states = phase8_state_by_key.get(key)
    if not states:
        return None
    return states.pop(0)


def _apply_phase8_state(transaction: Transaction, phase8_state: _Phase8State) -> None:
    transaction.include_in_expenses = phase8_state.include_in_expenses
    transaction.inclusion_initialized = phase8_state.inclusion_initialized
    transaction.inclusion_source = phase8_state.inclusion_source
    transaction.inclusion_updated_at = phase8_state.inclusion_updated_at
    transaction.review_status = phase8_state.review_status
    transaction.review_source = phase8_state.review_source
    transaction.review_updated_at = phase8_state.review_updated_at


def _pop_reusable_transaction(
    reusable_transactions_by_key: dict[tuple[str, str, Decimal, str], list[Transaction]],
    key: tuple[str, str, Decimal, str],
) -> Transaction | None:
    transactions = reusable_transactions_by_key.get(key)
    if not transactions:
        return None
    return transactions.pop(0)


def _new_extracted_transaction(
    statement_id: int,
    extraction_id: int,
    extracted: ExtractedTransaction,
) -> Transaction:
    transaction = Transaction(statement_id=statement_id)
    _apply_extracted_transaction(transaction, extraction_id, extracted)
    return transaction


def _apply_extracted_transaction(
    transaction: Transaction,
    extraction_id: int,
    extracted: ExtractedTransaction,
) -> None:
    transaction.extraction_id = extraction_id
    transaction.transaction_date = extracted.transaction_date
    transaction.transaction_detail = extracted.transaction_detail
    transaction.amount = extracted.amount
    transaction.direction = extracted.direction
    transaction.source_page = extracted.source_page
    transaction.source_order = extracted.source_order
    transaction.extraction_confidence = extracted.extraction_confidence
    transaction.needs_review = extracted.needs_review
    transaction.user_edited = False
    transaction.user_added = False
    transaction.excluded = False
    transaction.source = SOURCE_EXTRACTED
    transaction.original_transaction_date = extracted.transaction_date
    transaction.original_transaction_detail = extracted.transaction_detail
    transaction.original_amount = extracted.amount
    transaction.original_direction = extracted.direction
    transaction.original_source_page = extracted.source_page
    transaction.original_source_order = extracted.source_order


def _semantic_key_from_extracted(transaction: ExtractedTransaction) -> tuple[str, str, Decimal, str]:
    return (
        transaction.transaction_date.isoformat(),
        normalize_spaces(transaction.transaction_detail).casefold(),
        Decimal(transaction.amount).quantize(Decimal("0.01")),
        transaction.direction,
    )


def _semantic_key_from_transaction(transaction: Transaction) -> tuple[str, str, Decimal, str]:
    transaction_date = transaction.original_transaction_date or transaction.transaction_date
    transaction_detail = transaction.original_transaction_detail or transaction.transaction_detail
    amount = transaction.original_amount or transaction.amount
    direction = transaction.original_direction or transaction.direction
    return (
        transaction_date.isoformat(),
        normalize_spaces(transaction_detail).casefold(),
        Decimal(amount).quantize(Decimal("0.01")),
        direction,
    )


def _status_for_extraction(extracted_count: int, review_count: int, message: str | None) -> str:
    if extracted_count == 0:
        return STATUS_NEEDS_REVIEW
    if review_count > 0 or message:
        return STATUS_NEEDS_REVIEW
    return STATUS_EXTRACTED


def _latest_extraction(session: Session, statement_id: int) -> TransactionExtraction | None:
    return session.execute(
        select(TransactionExtraction)
        .where(TransactionExtraction.statement_id == statement_id)
        .order_by(desc(TransactionExtraction.started_at), desc(TransactionExtraction.id))
    ).scalars().first()


def _list_transactions(
    session: Session,
    statement_id: int,
    *,
    include_excluded: bool = False,
) -> list[Transaction]:
    statement = select(Transaction).where(Transaction.statement_id == statement_id)
    if not include_excluded:
        statement = statement.where(Transaction.excluded.is_(False))
    return list(
        session.execute(
            statement.order_by(Transaction.source_order.asc(), Transaction.id.asc())
        ).scalars().all()
    )


def _next_source_order(session: Session, statement_id: int) -> int:
    current_max = session.execute(
        select(func.max(Transaction.source_order)).where(Transaction.statement_id == statement_id)
    ).scalar_one()
    return int(current_max or 0) + 1


def _refresh_latest_counts(session: Session, statement_id: int) -> None:
    extraction = _latest_extraction(session, statement_id)
    if extraction is None:
        return
    active_transactions = _list_transactions(session, statement_id)
    extraction.transaction_count = len(active_transactions)
    extraction.review_count = sum(transaction.needs_review for transaction in active_transactions)


def _get_transaction_or_404(session: Session, transaction_id: int) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    return transaction


def _ensure_pdf_supported(statement: Statement) -> None:
    extension = Path(statement.file.display_name).suffix.lower()
    if statement.file.mime_type == "application/pdf" or extension == ".pdf":
        return
    raise HTTPException(status_code=415, detail="Transaction extraction is available for PDF files only.")
