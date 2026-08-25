from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


MONEY_TOKEN_RE = re.compile(
    r"(?P<amount>\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})\)?-?)"
)


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_money_token(value: str) -> tuple[Decimal, bool]:
    text = value.strip()
    is_negative = False

    if text.startswith("(") and text.endswith(")"):
        is_negative = True
        text = text[1:-1]
    if text.endswith("-"):
        is_negative = True
        text = text[:-1]
    if text.startswith("-"):
        is_negative = True
        text = text[1:]

    text = text.replace("$", "").replace(",", "").strip()
    try:
        amount = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid money amount.") from exc
    if amount < 0:
        is_negative = True
        amount = abs(amount)
    return amount, is_negative


def amount_at_end(value: str) -> tuple[str, Decimal, bool] | None:
    match = None
    for candidate in MONEY_TOKEN_RE.finditer(value):
        if not value[candidate.end() :].strip():
            match = candidate
            break
    if match is None:
        return None

    try:
        amount, is_negative = parse_money_token(match.group("amount"))
    except ValueError:
        return None
    detail = normalize_spaces(value[: match.start()])
    return detail, amount, is_negative


def is_amount_only(value: str) -> bool:
    return MONEY_TOKEN_RE.fullmatch(value.strip()) is not None


def resolve_transaction_date(
    month: int,
    day: int,
    explicit_year: int | None,
    statement_start_date: date | None,
    statement_end_date: date | None,
) -> tuple[date, bool]:
    years: Iterable[int]
    if explicit_year is not None:
        years = [explicit_year]
    elif statement_start_date is not None and statement_end_date is not None:
        years = dict.fromkeys([statement_start_date.year, statement_end_date.year]).keys()
    elif statement_end_date is not None:
        years = [statement_end_date.year]
    elif statement_start_date is not None:
        years = [statement_start_date.year]
    else:
        years = [datetime.now(UTC).year]

    candidates: list[date] = []
    for year in years:
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("Invalid transaction date.")

    if statement_start_date is not None and statement_end_date is not None:
        in_range = [
            candidate
            for candidate in candidates
            if statement_start_date <= candidate <= statement_end_date
        ]
        if in_range:
            return in_range[0], False

        def distance_from_period(candidate: date) -> int:
            if candidate < statement_start_date:
                return (statement_start_date - candidate).days
            return (candidate - statement_end_date).days

        return min(candidates, key=distance_from_period), True

    return candidates[0], statement_start_date is None and statement_end_date is None


def normalize_two_digit_year(value: str | None) -> int | None:
    if not value:
        return None
    if len(value) == 2:
        return 2000 + int(value)
    return int(value)
