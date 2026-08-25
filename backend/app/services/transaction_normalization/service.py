from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transaction import MerchantNormalizationRule, Transaction
from app.schemas.transaction import TransactionNormalizationUpdate
from app.services.transaction_extraction.service import get_statement_or_404
from app.services.transaction_normalization.base import (
    MATCH_EXACT,
    SOURCE_UNRESOLVED,
    SOURCE_USER_EDITED,
    STATUS_NOT_NORMALIZED,
    STATUS_USER_CONFIRMED,
    UserNormalizationRule,
)
from app.services.transaction_normalization.engine import normalize_transaction_detail
from app.services.transaction_normalization.text import derive_safe_rule_pattern, normalized_for_match


def normalize_transactions_for_statement(session: Session, statement_id: int) -> list[Transaction]:
    get_statement_or_404(session, statement_id)
    rules = _load_user_rules(session)
    active_transactions = _list_active_transactions(session, statement_id)
    now = datetime.now(UTC)

    for transaction in active_transactions:
        if transaction.user_edited_normalization:
            continue

        result = normalize_transaction_detail(transaction.transaction_detail, rules)
        _preserve_original_normalization(transaction, result)
        previous_state = (
            transaction.normalized_name,
            transaction.normalization_confidence,
            transaction.normalization_source,
            transaction.normalization_status,
            transaction.normalization_rule_id,
        )
        transaction.normalized_name = result.normalized_name
        transaction.normalization_confidence = result.confidence
        transaction.normalization_source = result.source
        transaction.normalization_status = result.status
        transaction.normalization_rule_id = result.rule_id
        transaction.normalized_at = now
        from app.services.transaction_review.service import sync_review_for_system_state

        sync_review_for_system_state(
            transaction,
            changed=previous_state
            != (
                transaction.normalized_name,
                transaction.normalization_confidence,
                transaction.normalization_source,
                transaction.normalization_status,
                transaction.normalization_rule_id,
            ),
        )

    session.commit()
    return _list_active_transactions(session, statement_id)


def update_transaction_normalization(
    session: Session,
    transaction_id: int,
    payload: TransactionNormalizationUpdate,
) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    if transaction.excluded:
        raise HTTPException(status_code=400, detail="Excluded transactions cannot be normalized from the active view.")

    _preserve_current_system_normalization(transaction)
    rule = None
    if payload.use_for_future:
        rule = _create_or_update_rule(session, transaction.transaction_detail, payload.normalized_name, payload.match_type)

    transaction.normalized_name = payload.normalized_name
    transaction.normalization_confidence = 1.0
    transaction.normalization_source = SOURCE_USER_EDITED
    transaction.normalization_status = STATUS_USER_CONFIRMED
    transaction.normalized_at = datetime.now(UTC)
    transaction.user_edited_normalization = True
    transaction.normalization_rule_id = rule.id if rule is not None else transaction.normalization_rule_id
    from app.services.transaction_type_detection.service import reset_machine_type

    reset_machine_type(transaction)
    from app.services.transaction_review.service import mark_review_needed_after_user_change

    mark_review_needed_after_user_change(transaction)
    session.commit()
    session.refresh(transaction)
    return transaction


def reset_machine_normalization(transaction: Transaction) -> None:
    if transaction.user_edited_normalization:
        return
    transaction.normalized_name = None
    transaction.normalization_confidence = 0.0
    transaction.normalization_source = SOURCE_UNRESOLVED
    transaction.normalization_status = STATUS_NOT_NORMALIZED
    transaction.normalized_at = None
    transaction.normalization_rule_id = None


def _load_user_rules(session: Session) -> list[UserNormalizationRule]:
    rules = session.execute(
        select(MerchantNormalizationRule).order_by(
            MerchantNormalizationRule.match_type.asc(),
            MerchantNormalizationRule.pattern.desc(),
        )
    ).scalars().all()
    return [
        UserNormalizationRule(
            id=rule.id,
            pattern=rule.pattern,
            normalized_name=rule.normalized_name,
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


def _preserve_original_normalization(transaction: Transaction, result) -> None:
    if transaction.original_normalization_status is not None:
        return
    transaction.original_normalized_name = result.normalized_name
    transaction.original_normalization_confidence = result.confidence
    transaction.original_normalization_source = result.source
    transaction.original_normalization_status = result.status


def _preserve_current_system_normalization(transaction: Transaction) -> None:
    if transaction.original_normalization_status is not None:
        return
    transaction.original_normalized_name = transaction.normalized_name
    transaction.original_normalization_confidence = transaction.normalization_confidence
    transaction.original_normalization_source = transaction.normalization_source
    transaction.original_normalization_status = transaction.normalization_status


def _create_or_update_rule(
    session: Session,
    raw_detail: str,
    normalized_name: str,
    match_type: str | None,
) -> MerchantNormalizationRule:
    pattern, derived_match_type = derive_safe_rule_pattern(raw_detail)
    selected_match_type = match_type or derived_match_type or MATCH_EXACT
    normalized_pattern = normalized_for_match(pattern)

    rule = session.execute(
        select(MerchantNormalizationRule).where(
            MerchantNormalizationRule.pattern == normalized_pattern,
            MerchantNormalizationRule.match_type == selected_match_type,
        )
    ).scalar_one_or_none()
    if rule is None:
        rule = MerchantNormalizationRule(
            pattern=normalized_pattern,
            normalized_name=normalized_name,
            match_type=selected_match_type,
            times_confirmed=1,
        )
        session.add(rule)
        session.flush()
        return rule

    rule.normalized_name = normalized_name
    rule.times_confirmed += 1
    session.flush()
    return rule
