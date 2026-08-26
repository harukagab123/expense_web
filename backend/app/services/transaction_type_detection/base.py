from __future__ import annotations

from dataclasses import dataclass


TYPE_EXPENSE = "EXPENSE"
TYPE_INCOME = "INCOME"
TYPE_TRANSFER = "TRANSFER"
TYPE_CREDIT_CARD_PAYMENT = "CREDIT_CARD_PAYMENT"
TYPE_REFUND = "REFUND"
TYPE_ATM_CASH_WITHDRAWAL = "ATM_CASH_WITHDRAWAL"
TYPE_CHECK = "CHECK"
TYPE_BANK_FEE = "BANK_FEE"
TYPE_INTEREST = "INTEREST"
TYPE_OTHER = "OTHER"
TYPE_UNKNOWN = "UNKNOWN"

TRANSACTION_TYPES = {
    TYPE_EXPENSE,
    TYPE_INCOME,
    TYPE_TRANSFER,
    TYPE_CREDIT_CARD_PAYMENT,
    TYPE_REFUND,
    TYPE_ATM_CASH_WITHDRAWAL,
    TYPE_CHECK,
    TYPE_BANK_FEE,
    TYPE_INTEREST,
    TYPE_OTHER,
    TYPE_UNKNOWN,
}

SOURCE_RULE = "RULE"
SOURCE_LEARNED_RULE = "LEARNED_RULE"
SOURCE_USER_EDITED = "USER_EDITED"
SOURCE_UNRESOLVED = "UNRESOLVED"

STATUS_NOT_CLASSIFIED = "NOT_CLASSIFIED"
STATUS_CLASSIFIED = "CLASSIFIED"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_USER_CONFIRMED = "USER_CONFIRMED"

INCLUDE_YES = "YES"
INCLUDE_NO = "NO"
INCLUDE_REVIEW = "REVIEW"

MATCH_EXACT = "EXACT"
MATCH_PREFIX = "PREFIX"
MATCH_CONTAINS = "CONTAINS"
MATCH_REGEX = "REGEX"


@dataclass(frozen=True)
class TypeClassificationResult:
    transaction_type: str
    confidence: float
    source: str
    status: str
    suggested_include: str
    rule_id: int | None = None


@dataclass(frozen=True)
class TypeClassificationInput:
    transaction_detail: str
    normalized_name: str | None
    direction: str
    statement_institution: str
    account_type: str
    interpreted_detail: str | None = None


@dataclass(frozen=True)
class UserTypeRule:
    id: int
    pattern: str
    transaction_type: str
    match_type: str
