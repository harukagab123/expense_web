from datetime import date

import pytest

from app.services.statement_detection.common import extract_account_last_four, extract_statement_period
from app.services.statement_detection.detector import detect_statement_text


CHASE_TEXT = """
JPMorgan Chase Bank, N.A.
Chase Total Checking Statement
Statement Period 08/11/2026 - 09/08/2026
Account ending in 4205
Beginning Balance
Deposits and Additions
Withdrawals and Deductions
Ending Balance
Transaction Detail
Capital One Mobile Pmt
American Express ACH Pmt
TJX Rewards Mastercard Payment
"""


def test_detects_chase_statement_and_ignores_transaction_institution_names() -> None:
    result = detect_statement_text(CHASE_TEXT, filename="statement.pdf")

    assert result.document_type == "BANK_STATEMENT"
    assert result.institution == "CHASE"
    assert result.product_name is None
    assert result.account_type == "CHECKING"
    assert result.account_last_four == "4205"
    assert result.statement_start_date == date(2026, 8, 11)
    assert result.statement_end_date == date(2026, 9, 8)
    assert result.status == "DETECTED"
    assert result.confidence > 0.75


def test_strong_chase_scores_higher_than_weak_chase_mention() -> None:
    strong = detect_statement_text(CHASE_TEXT)
    weak = detect_statement_text("Meeting notes mention Chase once and do not contain a statement header.")

    assert strong.confidence > weak.confidence
    assert weak.status in {"NEEDS_REVIEW", "NOT_A_STATEMENT"}


def test_detects_capital_one_statement() -> None:
    result = detect_statement_text(
        """
        Capital One Bank
        Credit Card Account Summary
        Statement Period 08/11/2026 to 09/08/2026
        Account Number: XXXX1234
        Payment Due Date
        Minimum Payment
        New Balance
        """,
    )

    assert result.institution == "CAPITAL_ONE"
    assert result.document_type == "CREDIT_CARD_STATEMENT"
    assert result.account_last_four == "1234"


def test_capital_one_card_signals_override_incidental_savings_language() -> None:
    result = detect_statement_text(
        """
        Capital One
        Quicksilver Mastercard
        Dec 03, 2024 - Jan 02, 2025
        Credit Limit
        Minimum Payment Due
        Estimated savings if balance paid off
        """,
    )

    assert result.account_type == "CREDIT_CARD"
    assert result.document_type == "CREDIT_CARD_STATEMENT"
    assert result.statement_start_date == date(2024, 12, 3)
    assert result.statement_end_date == date(2025, 1, 2)


def test_detects_american_express_statement() -> None:
    result = detect_statement_text(
        """
        American Express
        Cardmember Statement
        Statement Period August 11, 2026 through September 8, 2026
        Card ending 3792
        Payment Due
        Minimum Payment Due
        New Balance
        """,
    )

    assert result.institution == "AMEX"
    assert result.document_type == "CREDIT_CARD_STATEMENT"
    assert result.account_type == "CREDIT_CARD"
    assert result.account_last_four == "3792"


def test_detects_paypal_activity_statement() -> None:
    result = detect_statement_text(
        """
        PayPal Account
        Activity Statement
        Activity Period 08/11/26 to 09/08/26
        PayPal Balance
        Transaction Activity
        Account ending in 9988
        """,
    )

    assert result.institution == "PAYPAL"
    assert result.document_type == "PAYMENT_ACCOUNT_STATEMENT"
    assert result.account_type == "PAYMENT_ACCOUNT"
    assert result.account_last_four == "9988"


def test_detects_tjx_statement() -> None:
    result = detect_statement_text(
        """
        TJX Rewards Platinum Mastercard
        Synchrony Bank
        Statement Period 08/11/2026 - 09/08/2026
        Account Summary
        Payment Due
        New Balance
        """,
    )

    assert result.institution == "TJX"
    assert result.product_name == "TJX Rewards Platinum Mastercard"
    assert result.document_type == "CREDIT_CARD_STATEMENT"


def test_detects_amazon_chase_product_without_losing_issuer() -> None:
    result = detect_statement_text(
        """
        JPMorgan Chase Bank
        Amazon Prime Visa
        Statement Period 08/11/2026 - 09/08/2026
        Account Summary
        Payment Due
        New Balance
        """,
    )

    assert result.institution == "CHASE"
    assert result.product_name == "Amazon Prime Visa"
    assert result.document_type == "CREDIT_CARD_STATEMENT"


def test_detects_amazon_store_card_as_other_bank_product() -> None:
    result = detect_statement_text(
        """
        Amazon Store Card
        Synchrony Bank
        Statement Period 08/11/2026 - 09/08/2026
        Account Summary
        Payment Due
        New Balance
        """,
    )

    assert result.institution == "OTHER_BANK"
    assert result.product_name == "Amazon Store Card"
    assert result.document_type == "CREDIT_CARD_STATEMENT"


def test_other_document_is_not_a_statement() -> None:
    result = detect_statement_text(
        """
        Meeting Notes
        Project Summary
        Personal Document
        Remember to renew the parking permit.
        """,
    )

    assert result.document_type == "OTHER_DOCUMENT"
    assert result.institution == "UNKNOWN"
    assert result.status == "NOT_A_STATEMENT"


def test_ambiguous_financial_document_needs_review() -> None:
    result = detect_statement_text(
        """
        Account Overview
        Statement Details
        Balance information
        Payment information
        """,
    )

    assert result.document_type == "UNKNOWN"
    assert result.institution == "UNKNOWN"
    assert result.status == "NEEDS_REVIEW"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Statement Period 08/11/2026 - 09/08/2026", (date(2026, 8, 11), date(2026, 9, 8))),
        (
            "Statement Period August 11, 2026 through September 8, 2026",
            (date(2026, 8, 11), date(2026, 9, 8)),
        ),
        (
            "August 09, 2025throughSeptember 09, 2025",
            (date(2025, 8, 9), date(2025, 9, 9)),
        ),
        ("Statement Period 08/11/26 to 09/08/26", (date(2026, 8, 11), date(2026, 9, 8))),
    ],
)
def test_extracts_statement_period_formats(text: str, expected: tuple[date, date]) -> None:
    assert extract_statement_period(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Account ending in 4205", "4205"),
        ("Account Number: XXXX4205", "4205"),
        ("Card ending 3792", "3792"),
        ("Account Number: 1234 5678 9012 3456", "3456"),
    ],
)
def test_extracts_last_four_only(text: str, expected: str) -> None:
    assert extract_account_last_four(text) == expected
