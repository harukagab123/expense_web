from datetime import date
from decimal import Decimal

import pytest

from app.services.transaction_extraction.base import PageText, ParserContext
from app.services.transaction_extraction.chase import ChaseTransactionParser
from app.services.transaction_extraction.common import parse_money_token


def chase_context(start: date = date(2026, 8, 11), end: date = date(2026, 9, 8)) -> ParserContext:
    return ParserContext(
        institution="CHASE",
        product_name=None,
        account_type="CHECKING",
        statement_start_date=start,
        statement_end_date=end,
    )


def test_chase_parser_extracts_sections_and_multiline_descriptions() -> None:
    result = ChaseTransactionParser().parse(
        [
            PageText(
                page_number=1,
                text="""
                JPMorgan Chase Bank
                Statement Period 08/11/2026 - 09/08/2026
                Account Summary
                Beginning Balance 1,000.00
                Transaction Detail
                Deposits and Additions
                Date Description Amount
                08/15 PAYROLL ACME INC 1,250.00
                Total Deposits and Additions 1,250.00
                ATM & Debit Card Withdrawals
                08/18 AMAZON MKTPL*12345
                      AMZN.COM/BILL WA
                      147.29
                08/20 CHEVRON 0094821 FREMONT CA 64.29
                Electronic Withdrawals
                08/20 PAYMENT TO CHASE CARD 500.00
                Fees
                08/25 Monthly Service Fee 12.00
                Daily Ending Balance
                08/31 Ending Balance 1,526.42
                Page 1 of 1
                """,
            )
        ],
        chase_context(),
    )

    assert len(result.transactions) == 5
    assert [transaction.direction for transaction in result.transactions] == [
        "INFLOW",
        "OUTFLOW",
        "OUTFLOW",
        "OUTFLOW",
        "OUTFLOW",
    ]
    assert result.transactions[0].transaction_date == date(2026, 8, 15)
    assert result.transactions[0].amount == Decimal("1250.00")
    assert result.transactions[1].transaction_detail == "AMAZON MKTPL*12345 AMZN.COM/BILL WA"
    assert result.transactions[1].amount == Decimal("147.29")
    assert result.transactions[1].source_order == 2
    assert all(not transaction.needs_review for transaction in result.transactions)


def test_chase_parser_ignores_repeated_headers_and_tracks_source_pages() -> None:
    result = ChaseTransactionParser().parse(
        [
            PageText(
                page_number=1,
                text="""
                Transaction Detail
                Electronic Withdrawals
                Date Description Amount
                08/18 ONLINE TRANSFER TO SAVINGS 200.00
                Page 1 of 2
                """,
            ),
            PageText(
                page_number=2,
                text="""
                JPMorgan Chase Bank
                Account Number XXXX4205
                Page 2 of 2
                Transaction Detail
                Date Description Amount
                08/19 PAYMENT TO CHASE CARD 500.00
                Daily Ending Balance
                08/19 300.00
                """,
            ),
        ],
        chase_context(),
    )

    assert len(result.transactions) == 2
    assert result.transactions[0].source_page == 1
    assert result.transactions[1].source_page == 2
    assert [transaction.source_order for transaction in result.transactions] == [1, 2]
    assert result.transactions[1].transaction_detail == "PAYMENT TO CHASE CARD"


def test_chase_parser_resolves_december_january_statement_year_boundary() -> None:
    result = ChaseTransactionParser().parse(
        [
            PageText(
                page_number=1,
                text="""
                Transaction Detail
                ATM & Debit Card Withdrawals
                12/20 GROCERY STORE 75.42
                01/03 COFFEE SHOP 42.19
                """,
            )
        ],
        chase_context(date(2025, 12, 15), date(2026, 1, 14)),
    )

    assert [transaction.transaction_date for transaction in result.transactions] == [
        date(2025, 12, 20),
        date(2026, 1, 3),
    ]


def test_chase_parser_extracts_amount_balance_layout_from_running_balance() -> None:
    result = ChaseTransactionParser().parse(
        [
            PageText(
                page_number=1,
                text="""
                JPMorgan Chase Bank, N.A.
                August 09, 2025throughSeptember 09, 2025
                Beginning Balance $151.04
                Deposits and Additions 617.50
                ATM & Debit Card Withdrawals -60.00
                Electronic Withdrawals -100.00
                DATE DESCRIPTION AMOUNT BALANCE
                08/11 Zelle Payment From Example Person RefABC 651.04
                08/11 ATM Withdrawal 08/09 123 Main St Oakland CA Card 4205 - 60.00 591.04
                08/12 Capital One Mobile Pmt Web ID: 9279744380 - 100.00 491.04
                08/15 Payment Received 08/14 Example Merchant NV
                Card 4205
                608.54
                CHECKING SUMMARY
                Ending Balance $608.54
                """,
            )
        ],
        chase_context(date(2025, 8, 9), date(2025, 9, 9)),
    )

    assert [(transaction.transaction_date, transaction.transaction_detail) for transaction in result.transactions] == [
        (date(2025, 8, 11), "Zelle Payment From Example Person RefABC"),
        (date(2025, 8, 11), "ATM Withdrawal 08/09 123 Main St Oakland CA Card 4205"),
        (date(2025, 8, 12), "Capital One Mobile Pmt Web ID: 9279744380"),
        (date(2025, 8, 15), "Payment Received 08/14 Example Merchant NV Card 4205"),
    ]
    assert [transaction.amount for transaction in result.transactions] == [
        Decimal("500.00"),
        Decimal("60.00"),
        Decimal("100.00"),
        Decimal("117.50"),
    ]
    assert [transaction.direction for transaction in result.transactions] == [
        "INFLOW",
        "OUTFLOW",
        "OUTFLOW",
        "INFLOW",
    ]
    assert all(not transaction.needs_review for transaction in result.transactions)


def test_chase_balance_layout_ignores_summary_before_transaction_table() -> None:
    result = ChaseTransactionParser().parse(
        [
            PageText(
                page_number=1,
                text="""
                JPMorgan Chase Bank, N.A.
                March 11, 2025throughApril 08, 2025
                Beginning Balance $112.35
                Ending Balance $1,254.51
                Chase Total Checking
                Deposits and Additions 3,820.62
                ATM & Debit Card Withdrawals -516.60
                Electronic Withdrawals -2,934.19
                CHECKING SUMMARY
                DATE DESCRIPTION AMOUNT BALANCE
                03/14 Intempus Realty Payroll PPD ID: 9010258706 1,810.16
                CHECKING SUMMARY
                """,
            ),
            PageText(
                page_number=2,
                text="""
                DATE DESCRIPTION AMOUNT BALANCE
                March 11, 2025throughApril 08, 2025
                Account Number:
                03/14 Zelle Payment To Example Person - 200.00 1,610.16
                03/14 Capital One Mobile Pmt Web ID: 9279744380 - 254.03 1,356.13
                04/07 Card Purchase 04/05 Amazon Mktpl*1K8P551 Amzn.Com/Bill WA
                Card 8646
                - 101.62 1,254.51
                CHECKING SUMMARY
                Ending Balance $1,254.51
                """,
            ),
        ],
        chase_context(date(2025, 3, 11), date(2025, 4, 8)),
    )

    assert [transaction.transaction_detail for transaction in result.transactions] == [
        "Intempus Realty Payroll PPD ID: 9010258706",
        "Zelle Payment To Example Person",
        "Capital One Mobile Pmt Web ID: 9279744380",
        "Card Purchase 04/05 Amazon Mktpl*1K8P551 Amzn.Com/Bill WA Card 8646",
    ]
    assert [transaction.amount for transaction in result.transactions] == [
        Decimal("1697.81"),
        Decimal("200.00"),
        Decimal("254.03"),
        Decimal("101.62"),
    ]
    assert [transaction.direction for transaction in result.transactions] == [
        "INFLOW",
        "OUTFLOW",
        "OUTFLOW",
        "OUTFLOW",
    ]


def test_chase_parser_does_not_extract_summary_or_balance_lines() -> None:
    result = ChaseTransactionParser().parse(
        [
            PageText(
                page_number=1,
                text="""
                Beginning Balance 1,000.00
                Transaction Detail
                Deposits and Additions
                Total Deposits and Additions 1,250.00
                Withdrawals and Deductions
                Total Withdrawals and Deductions 600.00
                Daily Ending Balance
                08/20 Ending Balance 1,650.00
                """,
            )
        ],
        chase_context(),
    )

    assert result.transactions == []


@pytest.mark.parametrize(
    ("raw", "expected_amount", "expected_negative"),
    [
        ("100.00", Decimal("100.00"), False),
        ("1,250.00", Decimal("1250.00"), False),
        ("-75.42", Decimal("75.42"), True),
        ("($42.19)", Decimal("42.19"), True),
        ("75.42-", Decimal("75.42"), True),
    ],
)
def test_money_parser_preserves_exact_cents(raw: str, expected_amount: Decimal, expected_negative: bool) -> None:
    amount, is_negative = parse_money_token(raw)

    assert amount == expected_amount
    assert is_negative is expected_negative
