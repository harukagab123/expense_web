from __future__ import annotations

from dataclasses import dataclass, field
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
from app.services.transaction_extraction.common import normalize_spaces, parse_money_token, resolve_transaction_date


_DATE_RE = re.compile(r"^(?P<month>\d{2})/(?P<day>\d{2})$")
_AMOUNT_RE = re.compile(r"^-?\s*\$?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}$")
_CHECKING_STOP_RE = re.compile(r"^(?:total subtracted/added|all transaction times)", re.IGNORECASE)
_CREDIT_STOP_RE = re.compile(r"^(?:total fees|interest charged|citi flex plan details|202\d totals)", re.IGNORECASE)
_INFLOW_DETAIL_RE = re.compile(r"\b(?:credit|deposit|interest paid|refund)\b", re.IGNORECASE)


@dataclass
class _PendingRow:
    month: int
    day: int
    detail_parts: list[str] = field(default_factory=list)
    amounts: list[Decimal] = field(default_factory=list)
    negative: bool = False
    source_page: int = 1


class CitiTransactionParser:
    parser_name = "citi"
    parser_version = "citi-v1"

    def parse(self, pages: list[PageText], context: ParserContext) -> ParseResult:
        joined = "\n".join(page.text for page in pages).casefold()
        if "checking activity" in joined:
            return _parse_checking(pages, context)
        return _parse_credit_card(pages, context)


def _parse_checking(pages: list[PageText], context: ParserContext) -> ParseResult:
    transactions: list[ExtractedTransaction] = []
    pending: _PendingRow | None = None
    source_order = 1
    in_activity = False
    reading_table_header = False

    def finalize() -> None:
        nonlocal pending, source_order
        if pending is None or not pending.amounts:
            pending = None
            return
        detail = normalize_spaces(" ".join(pending.detail_parts))
        if not detail:
            pending = None
            return
        direction = DIRECTION_INFLOW if _INFLOW_DETAIL_RE.search(detail) else DIRECTION_OUTFLOW
        transaction_date, date_needs_review = resolve_transaction_date(
            pending.month,
            pending.day,
            None,
            context.statement_start_date,
            context.statement_end_date,
        )
        transactions.append(
            ExtractedTransaction(
                transaction_date=transaction_date,
                transaction_detail=detail,
                amount=pending.amounts[0],
                direction=direction,
                source_page=pending.source_page,
                source_order=source_order,
                extraction_confidence=0.72 if date_needs_review else 0.95,
                needs_review=date_needs_review,
            )
        )
        source_order += 1
        pending = None

    for page in pages:
        for raw_line in page.text.splitlines():
            line = normalize_spaces(raw_line)
            if not line:
                continue
            normalized = line.casefold()
            if normalized == "checking activity":
                finalize()
                in_activity = False
                reading_table_header = True
                continue
            if reading_table_header and normalized == "balance":
                in_activity = True
                reading_table_header = False
                continue
            if in_activity and _CHECKING_STOP_RE.match(line):
                finalize()
                in_activity = False
                continue
            if not in_activity:
                continue
            date_match = _DATE_RE.match(line)
            if date_match:
                finalize()
                pending = _PendingRow(
                    month=int(date_match.group("month")),
                    day=int(date_match.group("day")),
                    source_page=page.page_number,
                )
                continue
            if pending is None:
                continue
            if _AMOUNT_RE.fullmatch(line):
                amount, _ = parse_money_token(line)
                pending.amounts.append(amount)
                continue
            pending.detail_parts.append(line)

    finalize()
    return ParseResult(transactions=transactions)


def _parse_credit_card(pages: list[PageText], context: ParserContext) -> ParseResult:
    transactions: list[ExtractedTransaction] = []
    pending: _PendingRow | None = None
    source_order = 1
    in_activity = False

    def finalize() -> None:
        nonlocal pending, source_order
        if pending is None or not pending.amounts:
            pending = None
            return
        detail = normalize_spaces(" ".join(pending.detail_parts))
        if not detail:
            pending = None
            return
        transaction_date, date_needs_review = resolve_transaction_date(
            pending.month,
            pending.day,
            None,
            context.statement_start_date,
            context.statement_end_date,
        )
        transactions.append(
            ExtractedTransaction(
                transaction_date=transaction_date,
                transaction_detail=detail,
                amount=pending.amounts[0],
                direction=DIRECTION_INFLOW if pending.negative else DIRECTION_OUTFLOW,
                source_page=pending.source_page,
                source_order=source_order,
                extraction_confidence=0.72 if date_needs_review else 0.96,
                needs_review=date_needs_review,
            )
        )
        source_order += 1
        pending = None

    for page in pages:
        for raw_line in page.text.splitlines():
            line = normalize_spaces(raw_line)
            if not line:
                continue
            normalized = line.casefold()
            if normalized == "payments, credits and adjustments":
                finalize()
                in_activity = True
                continue
            if in_activity and _CREDIT_STOP_RE.match(line):
                finalize()
                in_activity = False
                continue
            if not in_activity:
                continue
            if pending is not None and pending.amounts:
                finalize()
            date_match = _DATE_RE.match(line)
            if date_match:
                if pending is not None and not pending.detail_parts and not pending.amounts:
                    continue
                finalize()
                pending = _PendingRow(
                    month=int(date_match.group("month")),
                    day=int(date_match.group("day")),
                    source_page=page.page_number,
                )
                continue
            if pending is None:
                continue
            if line == "-":
                pending.negative = True
                continue
            if _AMOUNT_RE.fullmatch(line):
                amount, negative = parse_money_token(line)
                pending.amounts.append(amount)
                pending.negative = pending.negative or negative
                continue
            if not normalized.startswith(("page ", "www.citicards.com", "customer service")):
                pending.detail_parts.append(line)

    finalize()
    return ParseResult(transactions=transactions)
