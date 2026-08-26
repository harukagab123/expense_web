from __future__ import annotations

from decimal import Decimal

from app.models.file import StoredFile
from app.models.folder import Folder
from app.models.statement import Statement
from app.models.transaction import Transaction
from app.services.attention.types import (
    SECTION_STATEMENT,
    SECTION_TRANSACTION,
    SEVERITY_ERROR,
    SEVERITY_REVIEW,
    AttentionFolderPathItem,
    AttentionItem,
)
from app.services.statement_detection.base import (
    DOCUMENT_BANK_STATEMENT,
    DOCUMENT_CREDIT_CARD_STATEMENT,
    DOCUMENT_PAYMENT_ACCOUNT_STATEMENT,
    DOCUMENT_UNKNOWN,
    INSTITUTION_UNKNOWN,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
)
from app.services.transaction_categorization.base import STATUS_NOT_APPLICABLE, UNCATEGORIZED
from app.services.transaction_review.service import REVIEW_REVIEWED


FINANCIAL_DOCUMENT_TYPES = {
    DOCUMENT_BANK_STATEMENT,
    DOCUMENT_CREDIT_CARD_STATEMENT,
    DOCUMENT_PAYMENT_ACCOUNT_STATEMENT,
}

KNOWN_NON_EXPENSE_TYPES = {
    "INCOME",
    "TRANSFER",
    "CREDIT_CARD_PAYMENT",
    "REFUND",
    "ATM_CASH_WITHDRAWAL",
    "CHECK",
}


def statement_attention_items(statement: Statement) -> list[AttentionItem]:
    file = statement.file
    items: list[AttentionItem] = []
    context = _statement_context(statement)

    if statement.detection_status == STATUS_FAILED:
        items.append(
            _statement_item(
                statement,
                "STATEMENT_DETECTION_FAILED",
                SEVERITY_ERROR,
                "Statement Detection Failed",
                statement.detection_reason or "The statement could not be analyzed reliably.",
                "detection_status",
                "detection_status=FAILED",
                blocking=True,
            )
        )
    elif statement.detection_status == STATUS_NEEDS_REVIEW and not _statement_metadata_was_resolved(statement):
        items.append(
            _statement_item(
                statement,
                "STATEMENT_NEEDS_REVIEW",
                SEVERITY_REVIEW,
                "Statement Needs Review",
                statement.detection_reason or context,
                "detection_status",
                "detection_status=NEEDS_REVIEW",
            )
        )

    if _unknown(statement.document_type) and not statement.user_corrected:
        items.append(
            _statement_item(
                statement,
                "STATEMENT_DOCUMENT_TYPE_UNKNOWN",
                SEVERITY_REVIEW,
                "Statement Document Type Unknown",
                file.display_name,
                "document_type",
                "document_type=UNKNOWN",
                blocking=True,
            )
        )

    if _unknown(statement.institution) and not statement.user_corrected:
        items.append(
            _statement_item(
                statement,
                "STATEMENT_INSTITUTION_UNKNOWN",
                SEVERITY_REVIEW,
                "Statement Institution Unknown",
                file.display_name,
                "institution",
                "institution=UNKNOWN",
                blocking=True,
            )
        )

    if _requires_account_type(statement) and _unknown(statement.account_type) and not statement.user_corrected:
        items.append(
            _statement_item(
                statement,
                "STATEMENT_ACCOUNT_TYPE_MISSING",
                SEVERITY_REVIEW,
                "Statement Account Type Missing",
                file.display_name,
                "account_type",
                "account_type=UNKNOWN",
                blocking=True,
            )
        )

    if _expects_statement_period(statement) and statement.statement_start_date is None:
        items.append(
            _statement_item(
                statement,
                "STATEMENT_START_DATE_MISSING",
                SEVERITY_REVIEW,
                "Statement Start Date Missing",
                file.display_name,
                "statement_start_date",
                "statement_start_date=NULL",
                blocking=True,
            )
        )

    if _expects_statement_period(statement) and statement.statement_end_date is None:
        items.append(
            _statement_item(
                statement,
                "STATEMENT_END_DATE_MISSING",
                SEVERITY_REVIEW,
                "Statement End Date Missing",
                file.display_name,
                "statement_end_date",
                "statement_end_date=NULL",
                blocking=True,
            )
        )

    return _dedupe(items)


def statement_transaction_review_attention_items(statement: Statement) -> list[AttentionItem]:
    active_transactions = [transaction for transaction in statement.transactions if not transaction.excluded]
    if not active_transactions:
        return []
    if all(transaction.review_status == REVIEW_REVIEWED for transaction in active_transactions):
        return []

    return [
        _statement_item(
            statement,
            "BANK_STATEMENT_REVIEW_REQUIRED",
            SEVERITY_REVIEW,
            "Bank Statement Must Be Reviewed",
            "Review this statement's transaction list.",
            "transaction_list_review",
            "transaction_review_status!=REVIEWED",
            blocking=True,
        )
    ]


def transaction_attention_items(transaction: Transaction) -> list[AttentionItem]:
    if transaction.excluded:
        return []

    items: list[AttentionItem] = []
    reviewed = transaction.review_status == REVIEW_REVIEWED
    included = transaction.include_in_expenses is True

    if _blank_date(transaction):
        items.append(
            _transaction_item(
                transaction,
                "TRANSACTION_DATE_MISSING",
                SEVERITY_ERROR,
                "Transaction Date Missing",
                "Transaction date is blank.",
                "transaction_date",
                "transaction_date=NULL",
                blocking=True,
            )
        )

    if _blank_amount(transaction):
        items.append(
            _transaction_item(
                transaction,
                "TRANSACTION_AMOUNT_MISSING",
                SEVERITY_ERROR,
                "Transaction Amount Missing",
                "Transaction amount is blank or invalid.",
                "amount",
                "amount=NULL",
                blocking=True,
            )
        )

    if not _present(transaction.transaction_detail):
        items.append(
            _transaction_item(
                transaction,
                "TRANSACTION_DETAIL_MISSING",
                SEVERITY_ERROR,
                "Transaction Detail Missing",
                "Transaction detail is blank.",
                "transaction_detail",
                "transaction_detail=BLANK",
                blocking=True,
            )
        )

    if transaction.needs_review and not reviewed:
        items.append(
            _transaction_item(
                transaction,
                "TRANSACTION_EXTRACTION_REVIEW",
                SEVERITY_REVIEW,
                "Extraction Needs Review",
                _transaction_description(transaction),
                "transaction_detail",
                "needs_review=true",
            )
        )

    if not included or reviewed:
        return _dedupe(items)

    if not _present(transaction.normalized_name):
        items.append(
            _transaction_item(
                transaction,
                "NORMALIZED_NAME_MISSING",
                SEVERITY_REVIEW,
                "Transaction Name Missing",
                _transaction_description(transaction),
                "normalized_name",
                "normalized_name=BLANK",
                blocking=True,
            )
        )
    elif transaction.normalization_status == "NEEDS_REVIEW":
        items.append(
            _transaction_item(
                transaction,
                "NORMALIZATION_NEEDS_REVIEW",
                SEVERITY_REVIEW,
                "Transaction Name Needs Review",
                _transaction_description(transaction),
                "normalized_name",
                "normalization_status=NEEDS_REVIEW",
            )
        )

    if _requires_category_completion(transaction):
        if not _present(transaction.main_category):
            items.append(
                _transaction_item(
                    transaction,
                    "CATEGORY_MISSING",
                    SEVERITY_REVIEW,
                    "Category Missing",
                    _transaction_description(transaction),
                    "main_category",
                    "main_category=BLANK",
                    blocking=True,
                )
            )
        elif not _present(transaction.subcategory):
            items.append(
                _transaction_item(
                    transaction,
                    "SUBCATEGORY_MISSING",
                    SEVERITY_REVIEW,
                    "Subcategory Missing",
                    _transaction_description(transaction),
                    "subcategory",
                    "subcategory=BLANK",
                    blocking=True,
                )
            )
        elif transaction.subcategory == UNCATEGORIZED:
            items.append(
                _transaction_item(
                    transaction,
                    "CATEGORY_UNCATEGORIZED",
                    SEVERITY_REVIEW,
                    "Uncategorized Expense",
                    _transaction_description(transaction),
                    "subcategory",
                    "subcategory=UNCATEGORIZED",
                    blocking=True,
                )
            )
        elif transaction.category_status == "NEEDS_REVIEW":
            items.append(
                _transaction_item(
                    transaction,
                    "CATEGORY_NEEDS_REVIEW",
                    SEVERITY_REVIEW,
                    "Category Needs Review",
                    _transaction_description(transaction),
                    "main_category",
                    "category_status=NEEDS_REVIEW",
                )
            )

    return _dedupe(items)


def _statement_item(
    statement: Statement,
    attention_type: str,
    severity: str,
    title: str,
    description: str,
    target_field: str,
    created_from_state: str,
    *,
    blocking: bool = False,
) -> AttentionItem:
    file = statement.file
    return AttentionItem(
        attention_id=f"{attention_type}:statement:{statement.id}:{target_field}",
        attention_type=attention_type,
        severity=severity,
        title=title,
        description=description,
        file_id=file.id,
        file_name=file.display_name,
        statement_id=statement.id,
        statement_label=_statement_context(statement),
        target_section=SECTION_STATEMENT,
        target_field=target_field,
        blocking=blocking,
        created_from_state=created_from_state,
        folder_path=_folder_path(file),
    )


def _transaction_item(
    transaction: Transaction,
    attention_type: str,
    severity: str,
    title: str,
    description: str,
    target_field: str,
    created_from_state: str,
    *,
    blocking: bool = False,
) -> AttentionItem:
    statement = transaction.statement
    file = statement.file
    return AttentionItem(
        attention_id=f"{attention_type}:transaction:{transaction.id}:{target_field}",
        attention_type=attention_type,
        severity=severity,
        title=title,
        description=description,
        file_id=file.id,
        file_name=file.display_name,
        statement_id=statement.id,
        statement_label=_statement_context(statement),
        transaction_id=transaction.id,
        transaction_date=transaction.transaction_date,
        transaction_name=transaction.normalized_name or transaction.transaction_detail,
        transaction_amount=Decimal(transaction.amount) if transaction.amount is not None else None,
        target_section=SECTION_TRANSACTION,
        target_field=target_field,
        blocking=blocking,
        created_from_state=created_from_state,
        folder_path=_folder_path(file),
    )


def _requires_category_completion(transaction: Transaction) -> bool:
    if transaction.category_status == STATUS_NOT_APPLICABLE:
        return False
    if transaction.transaction_type in KNOWN_NON_EXPENSE_TYPES:
        return False
    return True


def _requires_account_type(statement: Statement) -> bool:
    return statement.document_type in FINANCIAL_DOCUMENT_TYPES


def _expects_statement_period(statement: Statement) -> bool:
    return statement.document_type in FINANCIAL_DOCUMENT_TYPES


def _statement_metadata_was_resolved(statement: Statement) -> bool:
    if not statement.user_corrected:
        return False
    if statement.document_type == DOCUMENT_UNKNOWN or statement.institution == INSTITUTION_UNKNOWN:
        return False
    if _requires_account_type(statement) and _unknown(statement.account_type):
        return False
    if _expects_statement_period(statement) and (
        statement.statement_start_date is None or statement.statement_end_date is None
    ):
        return False
    return True


def _statement_context(statement: Statement) -> str:
    file_name = statement.file.display_name
    if statement.institution != INSTITUTION_UNKNOWN and statement.statement_end_date is not None:
        return f"{statement.institution} {statement.statement_end_date:%B %Y}"
    return file_name


def _transaction_description(transaction: Transaction) -> str:
    amount = "unknown amount" if transaction.amount is None else f"${Decimal(transaction.amount):,.2f}"
    date = "unknown date" if transaction.transaction_date is None else transaction.transaction_date.isoformat()
    return f"{transaction.normalized_name or transaction.transaction_detail} - {date} - {amount}"


def _folder_path(file: StoredFile) -> list[AttentionFolderPathItem]:
    folders: list[Folder] = []
    current = file.folder
    while current is not None:
        folders.append(current)
        current = current.parent
    return [
        AttentionFolderPathItem(id=folder.id, name=folder.name)
        for folder in reversed(folders)
    ]


def _unknown(value: str | None) -> bool:
    return value is None or value.strip() == "" or value == "UNKNOWN"


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _blank_date(transaction: Transaction) -> bool:
    return transaction.transaction_date is None


def _blank_amount(transaction: Transaction) -> bool:
    return transaction.amount is None


def _dedupe(items: list[AttentionItem]) -> list[AttentionItem]:
    seen: set[str] = set()
    unique: list[AttentionItem] = []
    for item in items:
        if item.attention_id in seen:
            continue
        seen.add(item.attention_id)
        unique.append(item)
    return unique
