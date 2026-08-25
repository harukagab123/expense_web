from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transaction import CategoryRule, Transaction
from app.schemas.transaction import TransactionCategoryBulkUpdate, TransactionCategoryUpdate
from app.services.transaction_categorization.base import (
    MATCH_EXACT,
    MATCH_NORMALIZED_NAME,
    SOURCE_USER_EDITED,
    SOURCE_UNRESOLVED,
    STATUS_NOT_CATEGORIZED,
    STATUS_USER_CONFIRMED,
    CategoryClassificationInput,
    CategoryClassificationResult,
    UserCategoryRule,
    is_category_eligible,
    not_applicable_result,
)
from app.services.transaction_categorization.engine import categorize_transaction
from app.services.transaction_extraction.service import get_statement_or_404
from app.services.transaction_normalization.text import derive_safe_rule_pattern, normalized_for_match


def categorize_transactions_for_statement(session: Session, statement_id: int) -> list[Transaction]:
    statement = get_statement_or_404(session, statement_id)
    rules = _load_user_rules(session)
    active_transactions = _list_active_transactions(session, statement_id)
    now = datetime.now(UTC)

    for transaction in active_transactions:
        previous_state = (
            transaction.main_category,
            transaction.subcategory,
            transaction.category_confidence,
            transaction.category_source,
            transaction.category_status,
            transaction.category_rule_id,
        )
        if not is_category_eligible(transaction.transaction_type, transaction.direction):
            _apply_category_result(transaction, not_applicable_result(), now)
            transaction.user_edited_category = False
            from app.services.transaction_review.service import sync_review_for_system_state

            sync_review_for_system_state(
                transaction,
                changed=previous_state
                != (
                    transaction.main_category,
                    transaction.subcategory,
                    transaction.category_confidence,
                    transaction.category_source,
                    transaction.category_status,
                    transaction.category_rule_id,
                ),
            )
            continue
        if transaction.user_edited_category:
            continue

        result = categorize_transaction(
            CategoryClassificationInput(
                transaction_detail=transaction.transaction_detail,
                normalized_name=transaction.normalized_name,
                transaction_type=transaction.transaction_type,
                direction=transaction.direction,
                statement_institution=statement.institution,
                account_type=statement.account_type,
            ),
            rules,
        )
        _preserve_original_category(transaction, result)
        _apply_category_result(transaction, result, now)
        from app.services.transaction_review.service import sync_review_for_system_state

        sync_review_for_system_state(
            transaction,
            changed=previous_state
            != (
                transaction.main_category,
                transaction.subcategory,
                transaction.category_confidence,
                transaction.category_source,
                transaction.category_status,
                transaction.category_rule_id,
            ),
        )

    session.commit()
    return _list_active_transactions(session, statement_id)


def update_transaction_category(
    session: Session,
    transaction_id: int,
    payload: TransactionCategoryUpdate,
) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    if transaction.excluded:
        raise HTTPException(status_code=400, detail="Excluded transactions cannot be categorized from the active view.")
    if not is_category_eligible(transaction.transaction_type, transaction.direction):
        raise HTTPException(status_code=400, detail="Change the transaction type before assigning an expense category.")

    _preserve_current_system_category(transaction)
    rule = None
    if payload.use_for_future:
        rule = _create_or_update_rule(
            session,
            transaction,
            payload.main_category,
            payload.subcategory,
            payload.match_type,
        )

    transaction.main_category = payload.main_category
    transaction.subcategory = payload.subcategory
    transaction.category_confidence = 1.0
    transaction.category_source = SOURCE_USER_EDITED
    transaction.category_status = STATUS_USER_CONFIRMED
    transaction.category_updated_at = datetime.now(UTC)
    transaction.user_edited_category = True
    transaction.category_rule_id = rule.id if rule is not None else transaction.category_rule_id
    from app.services.transaction_review.service import mark_review_needed_after_user_change

    mark_review_needed_after_user_change(transaction)
    session.commit()
    session.refresh(transaction)
    return transaction


def bulk_update_transaction_categories(
    session: Session,
    payload: TransactionCategoryBulkUpdate,
) -> tuple[list[Transaction], list[int]]:
    transactions = list(
        session.execute(select(Transaction).where(Transaction.id.in_(payload.transaction_ids))).scalars().all()
    )
    found_ids = {transaction.id for transaction in transactions}
    skipped_ids = [transaction_id for transaction_id in payload.transaction_ids if transaction_id not in found_ids]
    now = datetime.now(UTC)

    for transaction in transactions:
        if (
            transaction.excluded
            or not is_category_eligible(transaction.transaction_type, transaction.direction)
            or (transaction.user_edited_category and not payload.overwrite_user_edits)
        ):
            skipped_ids.append(transaction.id)
            continue
        _preserve_current_system_category(transaction)
        transaction.main_category = payload.main_category
        transaction.subcategory = payload.subcategory
        transaction.category_confidence = 1.0
        transaction.category_source = SOURCE_USER_EDITED
        transaction.category_status = STATUS_USER_CONFIRMED
        transaction.category_updated_at = now
        transaction.user_edited_category = True
        transaction.category_rule_id = None
        from app.services.transaction_review.service import mark_review_needed_after_user_change

        mark_review_needed_after_user_change(transaction)

    session.commit()
    for transaction in transactions:
        session.refresh(transaction)
    return transactions, skipped_ids


def reset_machine_category(transaction: Transaction) -> None:
    if transaction.user_edited_category:
        return
    transaction.main_category = None
    transaction.subcategory = None
    transaction.category_confidence = 0.0
    transaction.category_source = SOURCE_UNRESOLVED
    transaction.category_status = STATUS_NOT_CATEGORIZED
    transaction.category_updated_at = None
    transaction.category_rule_id = None


def reset_category_for_type_change(transaction: Transaction) -> None:
    if not is_category_eligible(transaction.transaction_type, transaction.direction):
        _apply_category_result(transaction, not_applicable_result(), datetime.now(UTC))
        transaction.user_edited_category = False
        transaction.category_rule_id = None
        return
    if transaction.category_status == "NOT_APPLICABLE":
        transaction.user_edited_category = False
    reset_machine_category(transaction)


def _apply_category_result(
    transaction: Transaction,
    result: CategoryClassificationResult,
    updated_at: datetime,
) -> None:
    transaction.main_category = result.main_category
    transaction.subcategory = result.subcategory
    transaction.category_confidence = result.confidence
    transaction.category_source = result.source
    transaction.category_status = result.status
    transaction.category_rule_id = result.rule_id
    transaction.category_updated_at = updated_at


def _load_user_rules(session: Session) -> list[UserCategoryRule]:
    rules = session.execute(
        select(CategoryRule).order_by(
            CategoryRule.match_type.asc(),
            CategoryRule.pattern.desc(),
        )
    ).scalars().all()
    return [
        UserCategoryRule(
            id=rule.id,
            pattern=rule.pattern,
            main_category=rule.main_category,
            subcategory=rule.subcategory,
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


def _preserve_original_category(transaction: Transaction, result: CategoryClassificationResult) -> None:
    if transaction.original_category_status is not None:
        return
    transaction.original_main_category = result.main_category
    transaction.original_subcategory = result.subcategory
    transaction.original_category_confidence = result.confidence
    transaction.original_category_source = result.source
    transaction.original_category_status = result.status


def _preserve_current_system_category(transaction: Transaction) -> None:
    if transaction.original_category_status is not None:
        return
    transaction.original_main_category = transaction.main_category
    transaction.original_subcategory = transaction.subcategory
    transaction.original_category_confidence = transaction.category_confidence
    transaction.original_category_source = transaction.category_source
    transaction.original_category_status = transaction.category_status


def _create_or_update_rule(
    session: Session,
    transaction: Transaction,
    main_category: str,
    subcategory: str,
    match_type: str | None,
) -> CategoryRule:
    normalized_name = normalized_for_match(transaction.normalized_name or "")
    if match_type == MATCH_NORMALIZED_NAME and normalized_name:
        pattern = normalized_name
        selected_match_type = MATCH_NORMALIZED_NAME
    else:
        pattern, derived_match_type = derive_safe_rule_pattern(transaction.transaction_detail)
        selected_match_type = match_type or derived_match_type or MATCH_EXACT

    normalized_pattern = normalized_for_match(pattern)
    if selected_match_type == "PREFIX" and normalized_pattern in {"AMAZON", "AMZN", "COSTCO"}:
        selected_match_type = MATCH_EXACT

    rule = session.execute(
        select(CategoryRule).where(
            CategoryRule.pattern == normalized_pattern,
            CategoryRule.match_type == selected_match_type,
        )
    ).scalar_one_or_none()
    if rule is None:
        rule = CategoryRule(
            pattern=normalized_pattern,
            main_category=main_category,
            subcategory=subcategory,
            match_type=selected_match_type,
            times_confirmed=1,
        )
        session.add(rule)
        session.flush()
        return rule

    rule.main_category = main_category
    rule.subcategory = subcategory
    rule.times_confirmed += 1
    session.flush()
    return rule
