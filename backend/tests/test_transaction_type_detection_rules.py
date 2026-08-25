from app.services.transaction_type_detection.base import (
    INCLUDE_NO,
    INCLUDE_REVIEW,
    INCLUDE_YES,
    STATUS_CLASSIFIED,
    STATUS_NEEDS_REVIEW,
    TYPE_ATM_CASH_WITHDRAWAL,
    TYPE_BANK_FEE,
    TYPE_CHECK,
    TYPE_CREDIT_CARD_PAYMENT,
    TYPE_EXPENSE,
    TYPE_INCOME,
    TYPE_INTEREST,
    TYPE_REFUND,
    TYPE_TRANSFER,
    TYPE_UNKNOWN,
    TypeClassificationInput,
)
from app.services.transaction_type_detection.engine import classify_transaction_type


def classify(raw_detail: str, direction: str = "OUTFLOW", normalized_name: str | None = None):
    return classify_transaction_type(
        TypeClassificationInput(
            transaction_detail=raw_detail,
            normalized_name=normalized_name,
            direction=direction,
            statement_institution="CHASE",
            account_type="CHECKING",
        )
    )


def test_credit_card_payments_are_not_expenses() -> None:
    examples = [
        "PAYMENT TO CHASE CARD ENDING IN 3792",
        "CAPITAL ONE MOBILE PMT",
        "AMERICAN EXPRESS ACH PMT",
        "TJX REW MSTRCRD SYF PAYMNT",
        "MACYS AUTO PYMT",
        "CHASE CREDIT CRD AUTOPAY",
        "CONCORA CREDIT PAYMENT",
    ]

    for raw_detail in examples:
        result = classify(raw_detail)
        assert result.transaction_type == TYPE_CREDIT_CARD_PAYMENT
        assert result.suggested_include == INCLUDE_NO
        assert result.status == STATUS_CLASSIFIED
        assert result.confidence >= 0.95


def test_expense_income_transfer_atm_check_fee_interest_rules() -> None:
    examples = [
        (classify("CHEVRON 0094821 FREMONT CA", "OUTFLOW", "Chevron"), TYPE_EXPENSE, INCLUDE_YES),
        (classify("INTEMPUS REALTY PAYROLL PPD ID: 123", "INFLOW"), TYPE_INCOME, INCLUDE_NO),
        (classify("ZELLE PAYMENT FROM JOHN DOE ABC12345", "INFLOW"), TYPE_TRANSFER, INCLUDE_NO),
        (classify("ZELLE PAYMENT TO JOHN DOE ABC12345", "OUTFLOW"), TYPE_TRANSFER, INCLUDE_NO),
        (classify("ATM WITHDRAWAL 08/24 MAIN ST", "OUTFLOW"), TYPE_ATM_CASH_WITHDRAWAL, INCLUDE_REVIEW),
        (classify("CHECK #1024", "OUTFLOW"), TYPE_CHECK, INCLUDE_REVIEW),
        (classify("MONTHLY SERVICE FEE", "OUTFLOW"), TYPE_BANK_FEE, INCLUDE_YES),
        (classify("INTEREST EARNED", "INFLOW"), TYPE_INTEREST, INCLUDE_REVIEW),
    ]

    for result, expected_type, expected_include in examples:
        assert result.transaction_type == expected_type
        assert result.suggested_include == expected_include
        assert result.status == STATUS_CLASSIFIED


def test_refunds_are_direction_sensitive_and_credit_card_payments_win_over_credit_word() -> None:
    refund = classify("MERCHANT CREDIT REFUND", "INFLOW")
    conflict = classify("MERCHANT CREDIT REFUND", "OUTFLOW")
    concora = classify("CONCORA CREDIT PAYMENT", "OUTFLOW")

    assert refund.transaction_type == TYPE_REFUND
    assert refund.suggested_include == INCLUDE_REVIEW
    assert conflict.transaction_type == TYPE_UNKNOWN
    assert conflict.status == STATUS_NEEDS_REVIEW
    assert concora.transaction_type == TYPE_CREDIT_CARD_PAYMENT


def test_unknown_and_direction_conflicts_need_review() -> None:
    unknown = classify("PAYMENT 83726", "OUTFLOW")
    payroll_conflict = classify("PAYROLL ACME INC", "OUTFLOW")
    zelle_unknown_direction = classify("ZELLE PAYMENT FROM JOHN DOE ABC12345", "UNKNOWN")

    assert unknown.transaction_type == TYPE_UNKNOWN
    assert unknown.status == STATUS_NEEDS_REVIEW
    assert unknown.suggested_include == INCLUDE_REVIEW
    assert unknown.confidence <= 0.25

    assert payroll_conflict.transaction_type == TYPE_UNKNOWN
    assert payroll_conflict.status == STATUS_NEEDS_REVIEW

    assert zelle_unknown_direction.transaction_type == TYPE_TRANSFER
    assert zelle_unknown_direction.status == STATUS_NEEDS_REVIEW
