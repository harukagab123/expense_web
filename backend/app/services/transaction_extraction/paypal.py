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
from app.services.transaction_extraction.common import normalize_spaces, resolve_transaction_date


_DATE_RE = re.compile(r"^(?P<month>\d{2})/(?P<day>\d{2})/(?P<year>\d{4})\s*(?P<detail>.*)$")
_MONEY_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d{2})")
_AMOUNT_ROW_RE = re.compile(r"^(?P<currency>[A-Z]{3})\s+(?P<values>.+)$")
_EXCHANGE_RATE_RE = re.compile(r"(?P<amount>\d+(?:\.\d{2})?)\s+USD\s+X\s+", re.IGNORECASE)


@dataclass
class _PendingTransaction:
    month: int
    day: int
    year: int
    detail_parts: list[str] = field(default_factory=list)
    source_page: int = 1


class PayPalTransactionParser:
    parser_name = "paypal"
    parser_version = "paypal-v1"

    def parse(self, pages: list[PageText], context: ParserContext) -> ParseResult:
        transactions: list[ExtractedTransaction] = []
        pending: _PendingTransaction | None = None
        source_order = 1
        in_paypal_account = False
        in_activity = False

        def append_transaction(amount: Decimal, direction: str, needs_review: bool) -> None:
            nonlocal pending, source_order
            if pending is None:
                return
            detail = normalize_spaces(" ".join(pending.detail_parts))
            if not detail:
                pending = None
                return
            transaction_date, date_needs_review = resolve_transaction_date(
                pending.month,
                pending.day,
                pending.year,
                context.statement_start_date,
                context.statement_end_date,
            )
            transactions.append(
                ExtractedTransaction(
                    transaction_date=transaction_date,
                    transaction_detail=detail,
                    amount=amount,
                    direction=direction,
                    source_page=pending.source_page,
                    source_order=source_order,
                    extraction_confidence=0.68 if needs_review or date_needs_review else 0.94,
                    needs_review=needs_review or date_needs_review,
                )
            )
            source_order += 1
            pending = None

        for page in pages:
            lines = _merge_wrapped_dates(page.text.splitlines())
            for raw_line in lines:
                line = normalize_spaces(raw_line)
                if not line:
                    continue
                normalized = line.casefold()

                if normalized == "paypal account":
                    pending = None
                    in_paypal_account = True
                    in_activity = False
                    continue
                if "paypal balance account" in normalized:
                    pending = None
                    in_paypal_account = False
                    in_activity = False
                    continue
                if in_paypal_account and normalized == "account activity":
                    pending = None
                    in_activity = True
                    continue
                if normalized.startswith("account statements"):
                    pending = None
                    in_activity = False
                    continue
                if not in_activity or normalized.startswith("date description currency"):
                    continue

                date_match = _DATE_RE.match(line)
                if date_match:
                    pending = _PendingTransaction(
                        month=int(date_match.group("month")),
                        day=int(date_match.group("day")),
                        year=int(date_match.group("year")),
                        detail_parts=_detail_parts(date_match.group("detail")),
                        source_page=page.page_number,
                    )
                    continue

                if pending is None:
                    continue
                amount_match = _AMOUNT_ROW_RE.match(line)
                if amount_match:
                    values = _MONEY_RE.findall(amount_match.group("values"))
                    if len(values) < 3:
                        continue
                    total = values[-1]
                    negative = total.startswith("-")
                    amount = Decimal(total.lstrip("+-").replace(",", ""))
                    needs_review = False
                    if amount_match.group("currency") != "USD":
                        exchange = _EXCHANGE_RATE_RE.search(" ".join(pending.detail_parts))
                        if exchange is None:
                            needs_review = True
                        else:
                            amount = Decimal(exchange.group("amount"))
                    append_transaction(
                        amount,
                        DIRECTION_OUTFLOW if negative else DIRECTION_INFLOW,
                        needs_review,
                    )
                    continue
                pending.detail_parts.extend(_detail_parts(line))

        return ParseResult(transactions=transactions)


def _merge_wrapped_dates(raw_lines: list[str]) -> list[str]:
    lines = [normalize_spaces(line) for line in raw_lines if normalize_spaces(line)]
    merged: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.fullmatch(r"\d{2}/\d{2}/\d{3}", line) and index + 1 < len(lines) and re.fullmatch(r"\d", lines[index + 1]):
            merged.append(f"{line}{lines[index + 1]}")
            index += 2
            continue
        merged.append(line)
        index += 1
    return merged


def _detail_parts(value: str) -> list[str]:
    line = normalize_spaces(value)
    if not line or re.match(r"^(?:id|ref id):", line, re.IGNORECASE):
        return []
    if _EXCHANGE_RATE_RE.search(line):
        return [line]
    return [line]
