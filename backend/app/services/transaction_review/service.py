from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.schemas.transaction import (
    TransactionInclusionBulkUpdate,
    TransactionInclusionUpdate,
    TransactionReviewBulkUpdate,
    TransactionReviewUpdate,
)

INCLUSION_UNINITIALIZED = "UNINITIALIZED"
INCLUSION_INITIAL_DEFAULT = "INITIAL_DEFAULT"
INCLUSION_USER_SELECTED = "USER_SELECTED"
INCLUSION_USER_EXCLUDED = "USER_EXCLUDED"
INCLUSION_BULK_USER_SELECTED = "BULK_USER_SELECTED"
INCLUSION_BULK_USER_EXCLUDED = "BULK_USER_EXCLUDED"
INCLUSION_RECORD_EXCLUDED = "RECORD_EXCLUDED"

REVIEW_PENDING = "PENDING"
REVIEW_NEEDS_REVIEW = "NEEDS_REVIEW"
REVIEW_REVIEWED = "REVIEWED"
REVIEW_SYSTEM = "SYSTEM"
REVIEW_USER_REVIEWED = "USER_REVIEWED"
REVIEW_USER_MARKED_NEEDS_REVIEW = "USER_MARKED_NEEDS_REVIEW"
REVIEW_DATA_CHANGED = "DATA_CHANGED"


def initialize_phase8_state_for_statement(session: Session, statement_id: int) -> list[Transaction]:
    transactions = list(
        session.execute(
            select(Transaction)
            .where(Transaction.statement_id == statement_id, Transaction.excluded.is_(False))
            .order_by(Transaction.source_order.asc(), Transaction.id.asc())
        ).scalars().all()
    )
    changed = initialize_phase8_state_for_transactions(transactions)
    if changed:
        session.commit()
        for transaction in transactions:
            session.refresh(transaction)
    return transactions


def initialize_phase8_state_for_transactions(transactions: list[Transaction]) -> bool:
    now = datetime.now(UTC)
    changed = False
    for transaction in transactions:
        changed = initialize_phase8_state(transaction, now=now) or changed
    return changed


def initialize_phase8_state(transaction: Transaction, *, now: datetime | None = None) -> bool:
    if transaction.excluded:
        return False

    updated_at = now or datetime.now(UTC)
    changed = False
    if not transaction.inclusion_initialized or transaction.include_in_expenses is None:
        transaction.include_in_expenses = True
        transaction.inclusion_initialized = True
        transaction.inclusion_source = INCLUSION_INITIAL_DEFAULT
        transaction.inclusion_updated_at = updated_at
        changed = True

    if transaction.review_updated_at is None:
        transaction.review_status = derived_review_status(transaction)
        transaction.review_source = REVIEW_SYSTEM
        transaction.review_updated_at = updated_at
        changed = True

    return changed


def derived_review_status(transaction: Transaction) -> str:
    return REVIEW_NEEDS_REVIEW if transaction_needs_review(transaction) else REVIEW_PENDING


def transaction_needs_review(transaction: Transaction) -> bool:
    return (
        bool(transaction.needs_review)
        or transaction.normalization_status == "NEEDS_REVIEW"
        or transaction.type_status == "NEEDS_REVIEW"
        or transaction.transaction_type == "UNKNOWN"
        or transaction.suggested_include == "REVIEW"
        or transaction.category_status in {"NEEDS_REVIEW", "NOT_CATEGORIZED"}
    )


def sync_review_for_system_state(transaction: Transaction, *, changed: bool = False) -> None:
    if transaction.excluded:
        return

    now = datetime.now(UTC)
    if transaction.review_status == REVIEW_REVIEWED and changed:
        transaction.review_status = REVIEW_NEEDS_REVIEW
        transaction.review_source = REVIEW_DATA_CHANGED
        transaction.review_updated_at = now
        return

    if transaction.review_status != REVIEW_REVIEWED:
        next_status = derived_review_status(transaction)
        if transaction.review_status != next_status or transaction.review_source != REVIEW_SYSTEM:
            transaction.review_status = next_status
            transaction.review_source = REVIEW_SYSTEM
            transaction.review_updated_at = now


def mark_review_needed_after_user_change(transaction: Transaction) -> None:
    if transaction.excluded:
        return
    transaction.review_status = REVIEW_NEEDS_REVIEW
    transaction.review_source = REVIEW_DATA_CHANGED
    transaction.review_updated_at = datetime.now(UTC)


def mark_transaction_record_excluded(transaction: Transaction) -> None:
    transaction.include_in_expenses = False
    transaction.inclusion_initialized = True
    transaction.inclusion_source = INCLUSION_RECORD_EXCLUDED
    transaction.inclusion_updated_at = datetime.now(UTC)


def update_transaction_inclusion(
    session: Session,
    transaction_id: int,
    payload: TransactionInclusionUpdate,
) -> Transaction:
    transaction = _get_active_transaction_or_404(session, transaction_id)
    initialize_phase8_state(transaction)
    _apply_inclusion(transaction, payload.include_in_expenses, bulk=False)
    session.commit()
    session.refresh(transaction)
    return transaction


def bulk_update_transaction_inclusion(
    session: Session,
    payload: TransactionInclusionBulkUpdate,
) -> tuple[list[Transaction], list[int]]:
    transactions = list(
        session.execute(select(Transaction).where(Transaction.id.in_(payload.transaction_ids))).scalars().all()
    )
    found_ids = {transaction.id for transaction in transactions}
    skipped_ids = [transaction_id for transaction_id in payload.transaction_ids if transaction_id not in found_ids]

    for transaction in transactions:
        if transaction.excluded:
            skipped_ids.append(transaction.id)
            continue
        initialize_phase8_state(transaction)
        _apply_inclusion(transaction, payload.include_in_expenses, bulk=True)

    session.commit()
    for transaction in transactions:
        session.refresh(transaction)
    return transactions, skipped_ids


def update_transaction_review(
    session: Session,
    transaction_id: int,
    payload: TransactionReviewUpdate,
) -> Transaction:
    transaction = _get_active_transaction_or_404(session, transaction_id)
    initialize_phase8_state(transaction)
    transaction.review_status = payload.review_status
    transaction.review_source = (
        REVIEW_USER_REVIEWED
        if payload.review_status == REVIEW_REVIEWED
        else REVIEW_USER_MARKED_NEEDS_REVIEW
    )
    transaction.review_updated_at = datetime.now(UTC)
    if payload.review_status == REVIEW_REVIEWED and transaction.main_category and transaction.subcategory:
        from app.services.statement_terminology.service import confirm_terms_from_category

        confirm_terms_from_category(session, transaction, transaction.main_category, transaction.subcategory)
    session.commit()
    session.refresh(transaction)
    return transaction


def bulk_update_transaction_review(
    session: Session,
    payload: TransactionReviewBulkUpdate,
) -> tuple[list[Transaction], list[int]]:
    transactions = list(
        session.execute(select(Transaction).where(Transaction.id.in_(payload.transaction_ids))).scalars().all()
    )
    found_ids = {transaction.id for transaction in transactions}
    skipped_ids = [transaction_id for transaction_id in payload.transaction_ids if transaction_id not in found_ids]
    now = datetime.now(UTC)

    for transaction in transactions:
        if transaction.excluded:
            skipped_ids.append(transaction.id)
            continue
        initialize_phase8_state(transaction, now=now)
        transaction.review_status = payload.review_status
        transaction.review_source = (
            REVIEW_USER_REVIEWED
            if payload.review_status == REVIEW_REVIEWED
            else REVIEW_USER_MARKED_NEEDS_REVIEW
        )
        transaction.review_updated_at = now
        if payload.review_status == REVIEW_REVIEWED and transaction.main_category and transaction.subcategory:
            from app.services.statement_terminology.service import confirm_terms_from_category

            confirm_terms_from_category(session, transaction, transaction.main_category, transaction.subcategory)

    session.commit()
    for transaction in transactions:
        session.refresh(transaction)
    return transactions, skipped_ids


def selected_amount(transactions: list[Transaction]) -> Decimal:
    total = Decimal("0.00")
    for transaction in transactions:
        if transaction.include_in_expenses is True and not transaction.excluded:
            total += Decimal(transaction.amount).quantize(Decimal("0.01"))
    return total.quantize(Decimal("0.01"))


def _apply_inclusion(transaction: Transaction, include: bool, *, bulk: bool) -> None:
    transaction.include_in_expenses = include
    transaction.inclusion_initialized = True
    if bulk:
        transaction.inclusion_source = INCLUSION_BULK_USER_SELECTED if include else INCLUSION_BULK_USER_EXCLUDED
    else:
        transaction.inclusion_source = INCLUSION_USER_SELECTED if include else INCLUSION_USER_EXCLUDED
    transaction.inclusion_updated_at = datetime.now(UTC)


def _get_active_transaction_or_404(session: Session, transaction_id: int) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    if transaction.excluded:
        raise HTTPException(status_code=400, detail="Excluded transactions cannot be changed from the active view.")
    return transaction
