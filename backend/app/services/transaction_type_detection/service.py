from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transaction import Transaction, TransactionTypeRule
from app.schemas.transaction import TransactionTypeBulkUpdate, TransactionTypeUpdate
from app.services.transaction_extraction.service import get_statement_or_404
from app.services.transaction_normalization.text import derive_safe_rule_pattern, normalized_for_match
from app.services.transaction_type_detection.base import (
    INCLUDE_REVIEW,
    MATCH_EXACT,
    SOURCE_UNRESOLVED,
    SOURCE_USER_EDITED,
    STATUS_NOT_CLASSIFIED,
    STATUS_USER_CONFIRMED,
    TYPE_UNKNOWN,
    TypeClassificationInput,
    TypeClassificationResult,
    UserTypeRule,
)
from app.services.transaction_type_detection.engine import classify_transaction_type
from app.services.transaction_type_detection.rules import suggested_include_for_type


def classify_transaction_types_for_statement(session: Session, statement_id: int) -> list[Transaction]:
    statement = get_statement_or_404(session, statement_id)
    rules = _load_user_rules(session)
    active_transactions = _list_active_transactions(session, statement_id)
    now = datetime.now(UTC)

    for transaction in active_transactions:
        if transaction.user_edited_type:
            continue

        result = classify_transaction_type(
            TypeClassificationInput(
                transaction_detail=transaction.transaction_detail,
                normalized_name=transaction.normalized_name,
                direction=transaction.direction,
                statement_institution=statement.institution,
                account_type=statement.account_type,
                interpreted_detail=transaction.interpreted_detail,
            ),
            rules,
        )
        _preserve_original_type(transaction, result)
        previous_state = (
            transaction.transaction_type,
            transaction.type_confidence,
            transaction.type_source,
            transaction.type_status,
            transaction.suggested_include,
            transaction.type_rule_id,
        )
        transaction.transaction_type = result.transaction_type
        transaction.type_confidence = result.confidence
        transaction.type_source = result.source
        transaction.type_status = result.status
        transaction.suggested_include = result.suggested_include
        transaction.type_rule_id = result.rule_id
        transaction.type_updated_at = now
        from app.services.transaction_categorization.service import reset_category_for_type_change

        reset_category_for_type_change(transaction)
        from app.services.transaction_review.service import sync_review_for_system_state

        sync_review_for_system_state(
            transaction,
            changed=previous_state
            != (
                transaction.transaction_type,
                transaction.type_confidence,
                transaction.type_source,
                transaction.type_status,
                transaction.suggested_include,
                transaction.type_rule_id,
            ),
        )

    session.commit()
    return _list_active_transactions(session, statement_id)


def update_transaction_type(
    session: Session,
    transaction_id: int,
    payload: TransactionTypeUpdate,
) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    if transaction.excluded:
        raise HTTPException(status_code=400, detail="Excluded transactions cannot be classified from the active view.")

    _preserve_current_system_type(transaction)
    rule = None
    if payload.use_for_future:
        rule = _create_or_update_rule(session, transaction.transaction_detail, payload.transaction_type, payload.match_type)

    transaction.transaction_type = payload.transaction_type
    transaction.type_confidence = 1.0
    transaction.type_source = SOURCE_USER_EDITED
    transaction.type_status = STATUS_USER_CONFIRMED
    transaction.suggested_include = suggested_include_for_type(payload.transaction_type, transaction.direction)
    transaction.type_updated_at = datetime.now(UTC)
    transaction.user_edited_type = True
    transaction.type_rule_id = rule.id if rule is not None else transaction.type_rule_id
    from app.services.transaction_categorization.service import reset_category_for_type_change

    reset_category_for_type_change(transaction)
    from app.services.transaction_review.service import mark_review_needed_after_user_change

    mark_review_needed_after_user_change(transaction)
    session.commit()
    session.refresh(transaction)
    return transaction


def bulk_update_transaction_types(
    session: Session,
    payload: TransactionTypeBulkUpdate,
) -> tuple[list[Transaction], list[int]]:
    transactions = list(
        session.execute(select(Transaction).where(Transaction.id.in_(payload.transaction_ids))).scalars().all()
    )
    found_ids = {transaction.id for transaction in transactions}
    skipped_ids = [transaction_id for transaction_id in payload.transaction_ids if transaction_id not in found_ids]
    now = datetime.now(UTC)

    for transaction in transactions:
        if transaction.excluded or (transaction.user_edited_type and not payload.overwrite_user_edits):
            skipped_ids.append(transaction.id)
            continue
        _preserve_current_system_type(transaction)
        transaction.transaction_type = payload.transaction_type
        transaction.type_confidence = 1.0
        transaction.type_source = SOURCE_USER_EDITED
        transaction.type_status = STATUS_USER_CONFIRMED
        transaction.suggested_include = suggested_include_for_type(payload.transaction_type, transaction.direction)
        transaction.type_updated_at = now
        transaction.user_edited_type = True
        transaction.type_rule_id = None
        from app.services.transaction_categorization.service import reset_category_for_type_change

        reset_category_for_type_change(transaction)
        from app.services.transaction_review.service import mark_review_needed_after_user_change

        mark_review_needed_after_user_change(transaction)

    session.commit()
    for transaction in transactions:
        session.refresh(transaction)
    return transactions, skipped_ids


def reset_machine_type(transaction: Transaction) -> None:
    # A user-confirmed category is downstream evidence that the current type is
    # intentionally expense-eligible. Invalidating that type after a name/detail
    # correction would also erase the manual category through
    # reset_category_for_type_change(). Keep both user-authoritative fields intact.
    if transaction.user_edited_type or transaction.user_edited_category:
        return
    transaction.transaction_type = TYPE_UNKNOWN
    transaction.type_confidence = 0.0
    transaction.type_source = SOURCE_UNRESOLVED
    transaction.type_status = STATUS_NOT_CLASSIFIED
    transaction.type_updated_at = None
    transaction.suggested_include = INCLUDE_REVIEW
    transaction.type_rule_id = None
    from app.services.transaction_categorization.service import reset_category_for_type_change

    reset_category_for_type_change(transaction)


def _load_user_rules(session: Session) -> list[UserTypeRule]:
    rules = session.execute(
        select(TransactionTypeRule).order_by(
            TransactionTypeRule.match_type.asc(),
            TransactionTypeRule.pattern.desc(),
        )
    ).scalars().all()
    return [
        UserTypeRule(
            id=rule.id,
            pattern=rule.pattern,
            transaction_type=rule.transaction_type,
            match_type=rule.match_type,
        )
        for rule in rules
    ]


def _list_active_transactions(session: Session, statement_id: int) -> list[Transaction]:
    return list(
        session.execute(
            select(Transaction)
            .where(Transaction.statement_id == statement_id, Transaction.excluded.is_(False))
            .order_by(Transaction.source_order.asc(), Transaction.id.asc())
        ).scalars().all()
    )


def _preserve_original_type(transaction: Transaction, result: TypeClassificationResult) -> None:
    if transaction.original_type_status is not None:
        return
    transaction.original_transaction_type = result.transaction_type
    transaction.original_type_confidence = result.confidence
    transaction.original_type_source = result.source
    transaction.original_type_status = result.status
    transaction.original_suggested_include = result.suggested_include


def _preserve_current_system_type(transaction: Transaction) -> None:
    if transaction.original_type_status is not None:
        return
    transaction.original_transaction_type = transaction.transaction_type
    transaction.original_type_confidence = transaction.type_confidence
    transaction.original_type_source = transaction.type_source
    transaction.original_type_status = transaction.type_status
    transaction.original_suggested_include = transaction.suggested_include


def _create_or_update_rule(
    session: Session,
    raw_detail: str,
    transaction_type: str,
    match_type: str | None,
) -> TransactionTypeRule:
    pattern, derived_match_type = derive_safe_rule_pattern(raw_detail)
    selected_match_type = match_type or derived_match_type or MATCH_EXACT
    normalized_pattern = normalized_for_match(pattern)

    rule = session.execute(
        select(TransactionTypeRule).where(
            TransactionTypeRule.pattern == normalized_pattern,
            TransactionTypeRule.match_type == selected_match_type,
        )
    ).scalar_one_or_none()
    if rule is None:
        rule = TransactionTypeRule(
            pattern=normalized_pattern,
            transaction_type=transaction_type,
            match_type=selected_match_type,
            times_confirmed=1,
        )
        session.add(rule)
        session.flush()
        return rule

    rule.transaction_type = transaction_type
    rule.times_confirmed += 1
    session.flush()
    return rule
