from __future__ import annotations

import re

from app.services.transaction_normalization.text import normalized_for_match
from app.services.transaction_type_detection.base import (
    INCLUDE_NO,
    INCLUDE_YES,
    INCLUDE_REVIEW,
    SOURCE_RULE,
    STATUS_CLASSIFIED,
    STATUS_NEEDS_REVIEW,
    TYPE_ATM_CASH_WITHDRAWAL,
    TYPE_BANK_FEE,
    TYPE_CHECK,
    TYPE_CREDIT_CARD_PAYMENT,
    TYPE_EXPENSE,
    TYPE_INCOME,
    TYPE_INTEREST,
    TYPE_OTHER,
    TYPE_REFUND,
    TYPE_TRANSFER,
    TYPE_UNKNOWN,
    TypeClassificationInput,
    TypeClassificationResult,
)


CREDIT_CARD_PAYMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAMEX\b.*\bACH\b.*\b(?:PMT|PAYMENT)\b"),
    re.compile(r"\bPAYMENT\s+TO\s+CHASE\s+CARD\b"),
    re.compile(r"\bCHASE\s+CREDIT\s+(?:CRD|CARD)\s+AUTOPAY\b"),
    re.compile(r"\bCAPITAL\s+ONE\b.*\b(?:MOBILE\s+)?PMT\b"),
    re.compile(r"\bCAPITAL\s+ONE\b.*\b(?:CRCARDPMT|CREDIT\s+CARD\s+PMT)\b"),
    re.compile(r"\bAMERICAN\s+EXPRESS\b.*\b(?:ACH\s+)?PMT\b"),
    re.compile(r"\bTJX\s+REW(?:ARDS)?\s+M(?:STRCRD|ASTERCARD)\b.*\b(?:SYF\s+)?PAYM?NT\b"),
    re.compile(r"\bMACY'?S\b.*\b(?:AUTO\s+)?PY?MT\b"),
    re.compile(r"\bCONCORA\s+CREDIT\b.*\bPAYMENT\b"),
    re.compile(r"\b(?:MOBILE|AUTOPAY)\s+PAYMENT\b.*\bTHANK\s+YOU\b"),
    re.compile(r"\bPAYMENT\s+THANK\s+YOU\b"),
)

ATM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bATM\s+(?:CASH\s+)?WITHDRAWAL\b"),
    re.compile(r"\bCASH\s+WITHDRAWAL\b"),
)

BANK_FEE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bMONTHLY\s+SERVICE\s+FEE\b"),
    re.compile(r"\bOVERDRAFT\s+FEE\b"),
    re.compile(r"\bWIRE\s+FEE\b"),
    re.compile(r"\bATM\s+FEE\b"),
    re.compile(r"\bFOREIGN\s+TRANSACTION\s+FEE\b"),
)

CHECK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^CHECK\s+#?\d+\b"),
)

REFUND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bREFUND\b"),
    re.compile(r"\bRETURN(?:ED)?\b"),
    re.compile(r"\bREVERSAL\b"),
    re.compile(r"\bMERCHANT\s+CREDIT\b"),
)

PAYROLL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bPAYROLL\b"),
    re.compile(r"\bDIRECT\s+DEP(?:OSIT)?\b"),
    re.compile(r"\bSALARY\b"),
    re.compile(r"\bWAGES\b"),
)

TRANSFER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bTRANSFER\s+(?:FROM|TO)\b"),
    re.compile(r"\bINTERNAL\s+TRANSFER\b"),
    re.compile(r"\bONLINE\s+TRANSFER\b"),
    re.compile(r"\bPAYPAL\s+TRANSFER\b"),
    re.compile(r"\bZELLE\s+(?:PAYMENT\s+)?(?:FROM|TO)\b"),
    re.compile(r"\bVENMO\s+(?:PAYMENT\s+)?(?:FROM|TO)\b"),
    re.compile(r"\bGENERAL\s+CREDIT\s+CARD\s+DEPOSIT\b"),
)

INTEREST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bINTEREST\s+(?:PAID|EARNED|CHARGE)\b"),
)

GENERIC_UNKNOWN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:PAYMENT|ACH|DBT\s+CRD)\s+\d+\b"),
    re.compile(r"^MISC\s+CREDIT\b"),
)


def match_known_type_rule(classification_input: TypeClassificationInput) -> TypeClassificationResult | None:
    raw = normalized_for_match(
        " ".join(
            value
            for value in (classification_input.transaction_detail, classification_input.interpreted_detail or "")
            if value
        )
    )
    name = normalized_for_match(classification_input.normalized_name or "")
    direction = classification_input.direction

    if _matches_any(raw, CREDIT_CARD_PAYMENT_PATTERNS):
        return _result(TYPE_CREDIT_CARD_PAYMENT, 0.99, direction)
    if _matches_any(raw, ATM_PATTERNS) or name == "ATM WITHDRAWAL":
        return _result(TYPE_ATM_CASH_WITHDRAWAL, 0.99, direction)
    if _matches_any(raw, BANK_FEE_PATTERNS) or name.endswith(" FEE"):
        return _result(TYPE_BANK_FEE, 0.96, direction)
    if _matches_any(raw, CHECK_PATTERNS) or re.fullmatch(r"CHECK\s+#?\d+", name):
        return _result(TYPE_CHECK, 0.94, direction)
    if _matches_any(raw, REFUND_PATTERNS):
        if direction == "INFLOW":
            return _result(TYPE_REFUND, 0.9, direction)
        return _result(TYPE_UNKNOWN, 0.42, direction, status=STATUS_NEEDS_REVIEW)
    if _matches_any(raw, PAYROLL_PATTERNS):
        if direction == "INFLOW":
            return _result(TYPE_INCOME, 0.95, direction)
        return _result(TYPE_UNKNOWN, 0.36, direction, status=STATUS_NEEDS_REVIEW)
    if _matches_any(raw, TRANSFER_PATTERNS):
        status = STATUS_CLASSIFIED if direction in {"INFLOW", "OUTFLOW"} else STATUS_NEEDS_REVIEW
        confidence = 0.78 if status == STATUS_CLASSIFIED else 0.52
        return _result(TYPE_TRANSFER, confidence, direction, status=status)
    if re.search(r"\bAUTOMATIC\s+PAYMENT\b", raw):
        return _result(TYPE_UNKNOWN, 0.58, direction, status=STATUS_NEEDS_REVIEW)
    if re.search(r"\bACH\s+PAYMENT\b", raw):
        return _result(TYPE_TRANSFER, 0.68, direction, status=STATUS_NEEDS_REVIEW)
    if raw.startswith("PAYMENT RECEIVED"):
        return _result(TYPE_OTHER, 0.62, direction, status=STATUS_NEEDS_REVIEW)
    if _matches_any(raw, INTEREST_PATTERNS):
        return _result(TYPE_INTEREST, 0.88, direction)
    if _matches_any(raw, GENERIC_UNKNOWN_PATTERNS):
        return _result(TYPE_UNKNOWN, 0.2, direction, status=STATUS_NEEDS_REVIEW)
    if direction == "OUTFLOW":
        confidence = 0.82 if classification_input.normalized_name else 0.72
        return _result(TYPE_EXPENSE, confidence, direction)
    if direction == "INFLOW":
        return _result(TYPE_OTHER, 0.55, direction, status=STATUS_NEEDS_REVIEW)
    return _result(TYPE_UNKNOWN, 0.2, direction, status=STATUS_NEEDS_REVIEW)


def suggested_include_for_type(transaction_type: str, direction: str) -> str:
    if transaction_type in {TYPE_EXPENSE, TYPE_BANK_FEE}:
        return INCLUDE_YES
    if transaction_type in {TYPE_CREDIT_CARD_PAYMENT, TYPE_INCOME}:
        return INCLUDE_NO
    if transaction_type == TYPE_TRANSFER:
        return INCLUDE_NO
    if transaction_type in {TYPE_REFUND, TYPE_ATM_CASH_WITHDRAWAL, TYPE_CHECK, TYPE_INTEREST, TYPE_OTHER, TYPE_UNKNOWN}:
        return INCLUDE_REVIEW
    if direction == "OUTFLOW":
        return INCLUDE_YES
    return INCLUDE_REVIEW


def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(value) is not None for pattern in patterns)


def _result(
    transaction_type: str,
    confidence: float,
    direction: str,
    *,
    status: str = STATUS_CLASSIFIED,
) -> TypeClassificationResult:
    return TypeClassificationResult(
        transaction_type=transaction_type,
        confidence=confidence,
        source=SOURCE_RULE,
        status=status,
        suggested_include=suggested_include_for_type(transaction_type, direction),
    )
