from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from app.services.transaction_extraction.base import (
    DIRECTION_INFLOW,
    DIRECTION_OUTFLOW,
    DIRECTION_UNKNOWN,
    ExtractedTransaction,
    PageText,
    ParseResult,
    ParserContext,
)
from app.services.transaction_extraction.common import (
    amount_at_end,
    is_amount_only,
    normalize_spaces,
    normalize_two_digit_year,
    parse_money_token,
    resolve_transaction_date,
)


DATE_PREFIX_RE = re.compile(
    r"^(?P<month>\d{1,2})[/-](?P<day>\d{1,2})(?:[/-](?P<year>\d{2,4}))?\s+(?P<rest>.+)$"
)
BALANCE_COLUMN_HEADER_RE = re.compile(r"\bdate\s+description\s+amount\s+balance\b", re.IGNORECASE)
BEGINNING_BALANCE_RE = re.compile(
    r"\bbeginning\s+balance\s+(?P<amount>\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})\)?-?)",
    re.IGNORECASE,
)
MONEY_VALUE_AT_END_RE = re.compile(
    r"(?P<amount>\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})\)?-?)\s*$"
)

SECTION_DIRECTIONS = {
    "deposits and additions": DIRECTION_INFLOW,
    "deposits": DIRECTION_INFLOW,
    "credits": DIRECTION_INFLOW,
    "payments and credits": DIRECTION_INFLOW,
    "atm & debit card withdrawals": DIRECTION_OUTFLOW,
    "atm/debit card withdrawals": DIRECTION_OUTFLOW,
    "electronic withdrawals": DIRECTION_OUTFLOW,
    "withdrawals and deductions": DIRECTION_OUTFLOW,
    "other withdrawals": DIRECTION_OUTFLOW,
    "checks paid": DIRECTION_OUTFLOW,
    "checks": DIRECTION_OUTFLOW,
    "fees": DIRECTION_OUTFLOW,
    "card purchases": DIRECTION_OUTFLOW,
    "purchases": DIRECTION_OUTFLOW,
}

STOP_HEADINGS = {
    "account summary",
    "balance summary",
    "checking summary",
    "daily ending balance",
    "daily balance detail",
    "service fee summary",
    "important information",
    "year-to-date totals",
    "rewards summary",
    "interest charges",
    "payment information",
}

IGNORED_EXACT = {
    "transaction detail",
    "date description amount",
    "date description amount balance",
    "date description withdrawals deposits balance",
    "date description additions subtractions balance",
    "beginning balance",
    "ending balance",
    "opening balance",
    "closing balance",
}

IGNORED_PREFIXES = (
    "account number",
    "page ",
    "statement period",
    "member fdic",
    "jpmorgan chase bank",
    "chase.com",
    "total deposits",
    "total withdrawals",
    "total fees",
    "total checks",
    "total card purchases",
    "total electronic withdrawals",
)


@dataclass
class PendingTransaction:
    month: int
    day: int
    year: int | None
    detail_parts: list[str]
    direction: str
    source_page: int
    section_known: bool


class ChaseTransactionParser:
    parser_name = "chase"
    parser_version = "chase-v1"

    def parse(self, pages: list[PageText], context: ParserContext) -> ParseResult:
        balance_column_result = _parse_balance_column_transactions(pages, context)
        if balance_column_result is not None:
            return balance_column_result

        transactions: list[ExtractedTransaction] = []
        pending: PendingTransaction | None = None
        current_direction: str | None = None
        source_order = 1

        for page in pages:
            for raw_line in page.text.splitlines():
                line = normalize_spaces(raw_line)
                if not line:
                    continue

                section_direction = _section_direction(line)
                if section_direction is not None:
                    pending = None
                    current_direction = section_direction
                    continue
                if _is_stop_heading(line):
                    pending = None
                    current_direction = None
                    continue
                if _is_ignored_line(line):
                    continue

                match = DATE_PREFIX_RE.match(line)
                if match:
                    pending = None
                    if current_direction is None:
                        continue
                    month = int(match.group("month"))
                    day = int(match.group("day"))
                    year = normalize_two_digit_year(match.group("year"))
                    rest = normalize_spaces(match.group("rest"))
                    amount_match = amount_at_end(rest)
                    section_known = True
                    direction = current_direction

                    if amount_match is None:
                        pending = PendingTransaction(
                            month=month,
                            day=day,
                            year=year,
                            detail_parts=[rest],
                            direction=direction,
                            source_page=page.page_number,
                            section_known=section_known,
                        )
                        continue

                    detail, amount, is_negative = amount_match
                    if direction == DIRECTION_UNKNOWN and is_negative:
                        direction = DIRECTION_OUTFLOW
                    transactions.append(
                        _build_transaction(
                            context=context,
                            month=month,
                            day=day,
                            year=year,
                            detail_parts=[detail],
                            amount=amount,
                            direction=direction,
                            source_page=page.page_number,
                            source_order=source_order,
                            section_known=section_known,
                        )
                    )
                    source_order += 1
                    continue

                if pending is None:
                    continue
                if _is_ignored_line(line) or _section_direction(line) is not None:
                    continue

                amount_match = amount_at_end(line)
                if amount_match is None:
                    if not is_amount_only(line):
                        pending.detail_parts.append(line)
                    continue

                detail_fragment, amount, is_negative = amount_match
                if detail_fragment:
                    pending.detail_parts.append(detail_fragment)
                direction = pending.direction
                if direction == DIRECTION_UNKNOWN and is_negative:
                    direction = DIRECTION_OUTFLOW
                transactions.append(
                    _build_transaction(
                        context=context,
                        month=pending.month,
                        day=pending.day,
                        year=pending.year,
                        detail_parts=pending.detail_parts,
                        amount=amount,
                        direction=direction,
                        source_page=pending.source_page,
                        source_order=source_order,
                        section_known=pending.section_known,
                    )
                )
                source_order += 1
                pending = None

        message = None
        if pending is not None:
            message = "One possible transaction line was skipped because no amount was found."
        return ParseResult(transactions=transactions, message=message)


def _parse_balance_column_transactions(pages: list[PageText], context: ParserContext) -> ParseResult | None:
    joined_text = "\n".join(page.text for page in pages)
    if BALANCE_COLUMN_HEADER_RE.search(joined_text) is None:
        return None

    current_balance = _find_beginning_balance(joined_text)
    if current_balance is None:
        return None

    transactions: list[ExtractedTransaction] = []
    pending: PendingTransaction | None = None
    source_order = 1
    table_started = False

    for page in pages:
        for raw_line in page.text.splitlines():
            line = normalize_spaces(raw_line)
            if not line:
                continue

            if BALANCE_COLUMN_HEADER_RE.search(line):
                table_started = True
                pending = None
                continue
            if not table_started:
                continue
            if _is_stop_heading(line):
                pending = None
                table_started = False
                continue
            if _is_ignored_line(line) or _section_direction(line) is not None:
                continue

            match = DATE_PREFIX_RE.match(line)
            if match:
                pending = None
                month = int(match.group("month"))
                day = int(match.group("day"))
                year = normalize_two_digit_year(match.group("year"))
                rest = normalize_spaces(match.group("rest"))
                balance_match = _money_value_at_end(rest)
                if balance_match is None:
                    pending = PendingTransaction(
                        month=month,
                        day=day,
                        year=year,
                        detail_parts=[rest],
                        direction=DIRECTION_UNKNOWN,
                        source_page=page.page_number,
                        section_known=True,
                    )
                    continue

                detail_fragment, ending_balance = balance_match
                built = _build_balance_delta_transaction(
                    context=context,
                    month=month,
                    day=day,
                    year=year,
                    detail_parts=[detail_fragment],
                    previous_balance=current_balance,
                    ending_balance=ending_balance,
                    source_page=page.page_number,
                    source_order=source_order,
                )
                current_balance = ending_balance
                transactions.append(built)
                source_order += 1
                continue

            if pending is None:
                continue
            if _is_ignored_line(line) or _section_direction(line) is not None:
                continue

            balance_match = _money_value_at_end(line)
            if balance_match is None:
                pending.detail_parts.append(line)
                continue

            detail_fragment, ending_balance = balance_match
            if detail_fragment:
                pending.detail_parts.append(detail_fragment)
            built = _build_balance_delta_transaction(
                context=context,
                month=pending.month,
                day=pending.day,
                year=pending.year,
                detail_parts=pending.detail_parts,
                previous_balance=current_balance,
                ending_balance=ending_balance,
                source_page=pending.source_page,
                source_order=source_order,
            )
            current_balance = ending_balance
            transactions.append(built)
            source_order += 1
            pending = None

    message = None
    if pending is not None:
        message = "One possible transaction line was skipped because no balance was found."
    return ParseResult(transactions=transactions, message=message)


def _build_balance_delta_transaction(
    *,
    context: ParserContext,
    month: int,
    day: int,
    year: int | None,
    detail_parts: list[str],
    previous_balance: Decimal,
    ending_balance: Decimal,
    source_page: int,
    source_order: int,
) -> ExtractedTransaction:
    delta = ending_balance - previous_balance
    amount = abs(delta).quantize(Decimal("0.01"))
    if delta > 0:
        direction = DIRECTION_INFLOW
    elif delta < 0:
        direction = DIRECTION_OUTFLOW
    else:
        direction = DIRECTION_UNKNOWN

    detail = _strip_duplicate_leading_date(normalize_spaces(" ".join(part for part in detail_parts if part)))
    detail = _strip_explicit_row_amount(detail, amount)
    return _build_transaction(
        context=context,
        month=month,
        day=day,
        year=year,
        detail_parts=[detail],
        amount=amount,
        direction=direction,
        source_page=source_page,
        source_order=source_order,
        section_known=True,
    )


def _build_transaction(
    *,
    context: ParserContext,
    month: int,
    day: int,
    year: int | None,
    detail_parts: list[str],
    amount,
    direction: str,
    source_page: int,
    source_order: int,
    section_known: bool,
) -> ExtractedTransaction:
    detail = normalize_spaces(" ".join(part for part in detail_parts if part))
    needs_review = False
    confidence = 0.96 if section_known else 0.72

    if not detail:
        detail = "UNKNOWN DESCRIPTION"
        needs_review = True
        confidence = min(confidence, 0.58)
    if direction == DIRECTION_UNKNOWN:
        needs_review = True
        confidence = min(confidence, 0.65)

    try:
        transaction_date, date_needs_review = resolve_transaction_date(
            month,
            day,
            year,
            context.statement_start_date,
            context.statement_end_date,
        )
    except ValueError:
        transaction_date, date_needs_review = resolve_transaction_date(
            month,
            day,
            None,
            context.statement_start_date,
            context.statement_end_date,
        )
        date_needs_review = True

    if date_needs_review:
        needs_review = True
        confidence = min(confidence, 0.7)

    if _looks_like_summary(detail):
        needs_review = True
        confidence = min(confidence, 0.55)

    return ExtractedTransaction(
        transaction_date=transaction_date,
        transaction_detail=detail,
        amount=amount,
        direction=direction,
        source_page=source_page,
        source_order=source_order,
        extraction_confidence=max(0.0, min(1.0, confidence)),
        needs_review=needs_review,
    )


def _find_beginning_balance(text: str) -> Decimal | None:
    match = BEGINNING_BALANCE_RE.search(text)
    if match is None:
        return None
    try:
        amount, is_negative = parse_money_token(match.group("amount"))
    except ValueError:
        return None
    return -amount if is_negative else amount


def _money_value_at_end(value: str) -> tuple[str, Decimal] | None:
    match = MONEY_VALUE_AT_END_RE.search(value)
    if match is None:
        return None
    try:
        amount, is_negative = parse_money_token(match.group("amount"))
    except ValueError:
        return None
    detail = normalize_spaces(value[: match.start()])
    signed_amount = -amount if is_negative else amount
    return detail, signed_amount


def _strip_duplicate_leading_date(value: str) -> str:
    return DATE_PREFIX_RE.sub(lambda match: normalize_spaces(match.group("rest")), value, count=1)


def _strip_explicit_row_amount(value: str, expected_amount: Decimal) -> str:
    match = MONEY_VALUE_AT_END_RE.search(value)
    if match is None:
        return value
    try:
        amount, _ = parse_money_token(match.group("amount"))
    except ValueError:
        return value
    if amount != expected_amount:
        return value
    prefix = value[: match.start()]
    if not re.search(r"[-+]\s*$", prefix):
        return value
    return normalize_spaces(re.sub(r"[-+]\s*$", "", prefix))


def _section_direction(line: str) -> str | None:
    normalized = _normalized_heading(line)
    exact = SECTION_DIRECTIONS.get(normalized)
    if exact is not None:
        return exact
    for heading, direction in SECTION_DIRECTIONS.items():
        if normalized.startswith(f"{heading} ") and _money_value_at_end(normalized) is not None:
            return direction
    return None


def _is_stop_heading(line: str) -> bool:
    normalized = _normalized_heading(line)
    return normalized in STOP_HEADINGS


def _is_ignored_line(line: str) -> bool:
    normalized = _normalized_heading(line)
    if normalized in IGNORED_EXACT:
        return True
    if any(normalized.startswith(prefix) for prefix in IGNORED_PREFIXES):
        return True
    if re.fullmatch(r"page \d+ of \d+", normalized):
        return True
    return _looks_like_summary(normalized)


def _looks_like_summary(value: str) -> bool:
    normalized = _normalized_heading(value)
    return any(
        phrase in normalized
        for phrase in (
            "beginning balance",
            "ending balance",
            "closing balance",
            "daily ending balance",
            "total deposits",
            "total withdrawals",
            "total fees",
            "statement period",
        )
    )


def _normalized_heading(line: str) -> str:
    return normalize_spaces(line).casefold().rstrip(":")


def parse_amount_for_tests(value: str):
    return parse_money_token(value)
