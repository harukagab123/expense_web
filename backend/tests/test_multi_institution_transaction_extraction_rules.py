from datetime import date
from decimal import Decimal

from app.services.statement_detection.detector import detect_statement_text
from app.services.transaction_extraction.amex import AmexTransactionParser
from app.services.transaction_extraction.base import PageText, ParserContext
from app.services.transaction_extraction.capital_one import CapitalOneTransactionParser
from app.services.transaction_extraction.citi import CitiTransactionParser
from app.services.transaction_extraction.paypal import PayPalTransactionParser


def parser_context(
    institution: str,
    account_type: str = "CREDIT_CARD",
    start: date = date(2025, 3, 1),
    end: date = date(2025, 4, 30),
) -> ParserContext:
    return ParserContext(
        institution=institution,
        product_name=None,
        account_type=account_type,
        statement_start_date=start,
        statement_end_date=end,
    )


def test_amex_parser_handles_wrapped_payments_charges_and_interest() -> None:
    result = AmexTransactionParser().parse(
        [
            PageText(
                page_number=3,
                text="""
                Payments and Credits
                Payments Amount
                03/15/25* MOBILE PAYMENT - THANK YOU -$200.00
                New Charges
                Detail
                Amount
                03/20/25 EXAMPLE MARKET SAN JOSE CA
                4085550100
                $31.20
                Interest Charged
                Amount
                04/10/25 Interest Charge on Pay Over Time Purchases $4.11
                Total Interest Charged for this Period $4.11
                """,
            ),
        ],
        parser_context("AMEX"),
    )

    assert [(transaction.transaction_detail, transaction.amount, transaction.direction) for transaction in result.transactions] == [
        ("MOBILE PAYMENT - THANK YOU", Decimal("200.00"), "INFLOW"),
        ("EXAMPLE MARKET SAN JOSE CA 4085550100", Decimal("31.20"), "OUTFLOW"),
        ("Interest Charge on Pay Over Time Purchases", Decimal("4.11"), "OUTFLOW"),
    ]


def test_capital_one_parser_reads_compressed_credit_card_rows() -> None:
    result = CapitalOneTransactionParser().parse(
        [
            PageText(
                page_number=3,
                text="""
                Transactions Visit capitalone.com to see detailed transactions.
                TEST USER #4482: Payments, Credits and Adjustments Trans Date Post Date Description Amount
                Mar 22 Mar 22 CAPITAL ONE MOBILE PYMT - $12.90
                TEST USER #4482: Transactions Trans Date Post Date Description Amount
                Mar 2 Mar 4 EXAMPLE CAFE SAN JOSE CA $26.00
                TEST USER #4482: Total Transactions $26.00
                Total Transactions for This Period $26.00
                Interest Charged Interest Charge on Purchases $1.23
                """,
            ),
            PageText(
                page_number=4,
                text="""
                Transactions (Continued) Trans Date Post Date Description Amount
                Mar 3 Mar 5 EXAMPLE MARKET SAN JOSE CA $7.50
                Total Transactions for This Period $33.50
                """,
            ),
        ],
        parser_context("CAPITAL_ONE"),
    )

    assert [(transaction.transaction_detail, transaction.amount, transaction.direction) for transaction in result.transactions] == [
        ("CAPITAL ONE MOBILE PYMT", Decimal("12.90"), "INFLOW"),
        ("EXAMPLE CAFE SAN JOSE CA", Decimal("26.00"), "OUTFLOW"),
        ("EXAMPLE MARKET SAN JOSE CA", Decimal("7.50"), "OUTFLOW"),
        ("Interest Charge on Purchases", Decimal("1.23"), "OUTFLOW"),
    ]


def test_paypal_parser_merges_wrapped_dates_and_ignores_reference_ids() -> None:
    result = PayPalTransactionParser().parse(
        [
            PageText(
                page_number=1,
                text="""
                PAYPAL ACCOUNT
                ACCOUNT ACTIVITY
                DATE DESCRIPTION CURRENCY AMOUNT FEES TOTAL*
                04/02/202
                5
                PreApproved Payment Bill User Payment:
                Apple Services
                ID: 58T97915N77156230
                USD -12.90 0.00 -12.90
                04/02/2025 General Credit Card Deposit
                Ref ID: 58T97915N77156230
                USD 12.90 0.00 12.90
                ACCOUNT STATEMENTS
                """,
            )
        ],
        parser_context("PAYPAL", "PAYMENT_ACCOUNT"),
    )

    assert [(transaction.transaction_detail, transaction.amount, transaction.direction) for transaction in result.transactions] == [
        ("PreApproved Payment Bill User Payment: Apple Services", Decimal("12.90"), "OUTFLOW"),
        ("General Credit Card Deposit", Decimal("12.90"), "INFLOW"),
    ]


def test_citi_checking_parser_uses_credit_and_debit_columns() -> None:
    result = CitiTransactionParser().parse(
        [
            PageText(
                page_number=2,
                text="""
                CHECKING ACTIVITY
                Date
                Description
                Amount Subtracted
                Amount Added
                Balance
                03/28
                ACH Electronic Debit
                Example Utility
                31.78
                182.87
                04/07
                Zelle Credit
                Example Sender
                250.00
                Total Subtracted/Added
                """,
            )
        ],
        parser_context("CITI", "CHECKING"),
    )

    assert [(transaction.transaction_detail, transaction.amount, transaction.direction) for transaction in result.transactions] == [
        ("ACH Electronic Debit Example Utility", Decimal("31.78"), "OUTFLOW"),
        ("Zelle Credit Example Sender", Decimal("250.00"), "INFLOW"),
    ]


def test_citi_credit_card_parser_handles_sale_and_post_dates() -> None:
    result = CitiTransactionParser().parse(
        [
            PageText(
                page_number=2,
                text="""
                Payments, Credits and Adjustments
                04/07
                PAYMENT THANK YOU
                -
                $400.00
                TEST USER
                Standard Purchases
                03/20
                03/22
                EXAMPLE RESTAURANT SAN JOSE CA
                $75.83
                Fees Charged
                TOTAL FEES FOR THIS PERIOD
                $0.00
                """,
            )
        ],
        parser_context("CITI"),
    )

    assert [(transaction.transaction_detail, transaction.amount, transaction.direction) for transaction in result.transactions] == [
        ("PAYMENT THANK YOU", Decimal("400.00"), "INFLOW"),
        ("EXAMPLE RESTAURANT SAN JOSE CA", Decimal("75.83"), "OUTFLOW"),
    ]


def test_citi_detection_preserves_its_statement_period() -> None:
    result = detect_statement_text(
        """
        CITIBANK, N.A.
        Statement Period - Mar 20 - Apr 20, 2025
        YOUR SIMPLIFIED BANKING ACCOUNT STATEMENT
        CHECKING ACTIVITY
        Account 42041176571
        """
    )

    assert result.institution == "CITI"
    assert result.account_type == "CHECKING"
    assert result.account_last_four == "6571"
    assert result.statement_start_date == date(2025, 3, 20)
    assert result.statement_end_date == date(2025, 4, 20)
