from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import re

from app.services.transaction_extraction.base import (
    DIRECTION_INFLOW,
    DIRECTION_OUTFLOW,
    ExtractedTransaction,
    PageText,
    ParseResult,
    ParserContext,
)
from app.services.transaction_extraction.common import normalize_spaces, resolve_transaction_date


_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_PATTERN = "|".join(_MONTHS)
_ROW_RE = re.compile(
    rf"(?P<month>{_MONTH_PATTERN})\s+(?P<day>\d{{1,2}})\s+"
    rf"(?:{_MONTH_PATTERN})\s+\d{{1,2}}\s+"
    r"(?P<detail>.*?)\s+(?P<negative>-\s*)?\$(?P<amount>[\d,]+\.\d{2})"
    rf"(?=\s+(?:(?:{_MONTH_PATTERN})\s+\d{{1,2}}\s+(?:{_MONTH_PATTERN})\s+\d{{1,2}}\s+|"
    r"[A-Z][A-Z .'-]+#\d{4}:\s+(?:Total\s+)?Transactions|"
    r"Total Transactions(?: for This Period)?|Fees\s+Trans Date|Interest Charged)|$)",
    re.IGNORECASE,
)
_INTEREST_RE = re.compile(
    r"(?P<detail>Interest Charge on [A-Za-z ]+?)\s+\$(?P<amount>[\d,]+\.\d{2})",
    re.IGNORECASE,
)


class CapitalOneTransactionParser:
    parser_name = "capital-one"
    parser_version = "capital-one-v1"

    def parse(self, pages: list[PageText], context: ParserContext) -> ParseResult:
        transactions: list[ExtractedTransaction] = []
        summary_charges: list[tuple[int, str, Decimal]] = []
        source_order = 1

        for page in pages:
            text = normalize_spaces(page.text)
            for match in _ROW_RE.finditer(text):
                month = _MONTHS[match.group("month").casefold()]
                transaction_date, date_needs_review = resolve_transaction_date(
                    month,
                    int(match.group("day")),
                    None,
                    context.statement_start_date,
                    context.statement_end_date,
                )
                detail = normalize_spaces(match.group("detail"))
                if not detail:
                    continue
                transactions.append(
                    ExtractedTransaction(
                        transaction_date=transaction_date,
                        transaction_detail=detail,
                        amount=Decimal(match.group("amount").replace(",", "")),
                        direction=DIRECTION_INFLOW if match.group("negative") else DIRECTION_OUTFLOW,
                        source_page=page.page_number,
                        source_order=source_order,
                        extraction_confidence=0.72 if date_needs_review else 0.97,
                        needs_review=date_needs_review,
                    )
                )
                source_order += 1

            for match in _INTEREST_RE.finditer(text):
                amount = Decimal(match.group("amount").replace(",", ""))
                if amount == Decimal("0.00"):
                    continue
                summary_charges.append((page.page_number, normalize_spaces(match.group("detail")), amount))

        transaction_date = context.statement_end_date or context.statement_start_date or datetime.now(UTC).date()
        for page_number, detail, amount in summary_charges:
            transactions.append(
                ExtractedTransaction(
                    transaction_date=transaction_date,
                    transaction_detail=detail,
                    amount=amount,
                    direction=DIRECTION_OUTFLOW,
                    source_page=page_number,
                    source_order=source_order,
                    extraction_confidence=0.86,
                    needs_review=context.statement_end_date is None and context.statement_start_date is None,
                )
            )
            source_order += 1

        return ParseResult(transactions=transactions)
