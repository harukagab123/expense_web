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
from app.services.transaction_extraction.common import normalize_spaces, normalize_two_digit_year, resolve_transaction_date


_DATE_RE = re.compile(
    r"^(?P<month>\d{2})/(?P<day>\d{2})/(?P<year>\d{2,4})\*?\s*(?P<detail>.*)$"
)
_AMOUNT_RE = re.compile(r"(?P<negative>-\s*)?\$(?P<amount>[\d,]+\.\d{2})")
_SECTION_PAYMENT = "PAYMENT"
_SECTION_CHARGE = "CHARGE"
_SECTION_FEE = "FEE"
_SECTION_INTEREST = "INTEREST"
_PENDING_SECTIONS = {
    "AWAIT_PAYMENT": _SECTION_PAYMENT,
    "AWAIT_CHARGE": _SECTION_CHARGE,
    "AWAIT_FEE": _SECTION_FEE,
    "AWAIT_INTEREST": _SECTION_INTEREST,
}


@dataclass
class _PendingTransaction:
    month: int
    day: int
    year: int | None
    detail_parts: list[str] = field(default_factory=list)
    section: str = _SECTION_CHARGE
    source_page: int = 1


class AmexTransactionParser:
    parser_name = "amex"
    parser_version = "amex-v1"

    def parse(self, pages: list[PageText], context: ParserContext) -> ParseResult:
        transactions: list[ExtractedTransaction] = []
        pending: _PendingTransaction | None = None
        section: str | None = None
        source_order = 1

        def finalize() -> None:
            nonlocal pending, source_order
            if pending is None:
                return
            pending = None

        def append_transaction(amount: Decimal, negative: bool) -> None:
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
            direction = DIRECTION_INFLOW if pending.section == _SECTION_PAYMENT or negative else DIRECTION_OUTFLOW
            transactions.append(
                ExtractedTransaction(
                    transaction_date=transaction_date,
                    transaction_detail=detail,
                    amount=amount,
                    direction=direction,
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

                if normalized == "payments and credits":
                    finalize()
                    section = "AWAIT_PAYMENT"
                    continue
                if normalized == "payments amount" and section == "AWAIT_PAYMENT":
                    section = _SECTION_PAYMENT
                    continue
                if normalized == "new charges":
                    finalize()
                    section = "AWAIT_CHARGE"
                    continue
                if normalized == "fees":
                    finalize()
                    section = "AWAIT_FEE"
                    continue
                if normalized == "interest charged":
                    finalize()
                    section = "AWAIT_INTEREST"
                    continue
                if normalized.startswith("detail continued"):
                    finalize()
                    section = _SECTION_CHARGE
                    continue
                if section == "AWAIT_CHARGE" and normalized.endswith(" amount"):
                    section = _SECTION_CHARGE
                    continue
                if normalized == "amount" and section in _PENDING_SECTIONS:
                    section = _PENDING_SECTIONS[section]
                    continue
                if normalized.startswith("total "):
                    finalize()
                    continue
                if normalized.startswith("p. ") or normalized.startswith("continued on"):
                    finalize()
                    continue

                date_match = _DATE_RE.match(line)
                if date_match and section in {_SECTION_PAYMENT, _SECTION_CHARGE, _SECTION_FEE, _SECTION_INTEREST}:
                    finalize()
                    detail = normalize_spaces(date_match.group("detail"))
                    amount_match = _AMOUNT_RE.search(detail)
                    if amount_match:
                        pending = _PendingTransaction(
                            month=int(date_match.group("month")),
                            day=int(date_match.group("day")),
                            year=normalize_two_digit_year(date_match.group("year")),
                            detail_parts=[normalize_spaces(detail[: amount_match.start()])],
                            section=section,
                            source_page=page.page_number,
                        )
                        append_transaction(
                            Decimal(amount_match.group("amount").replace(",", "")),
                            bool(amount_match.group("negative")),
                        )
                        continue
                    pending = _PendingTransaction(
                        month=int(date_match.group("month")),
                        day=int(date_match.group("day")),
                        year=normalize_two_digit_year(date_match.group("year")),
                        detail_parts=[detail],
                        section=section,
                        source_page=page.page_number,
                    )
                    continue

                if pending is None:
                    continue
                if normalized in {"amount", "detail", "card ending 4-71007"}:
                    continue
                amount_match = _AMOUNT_RE.search(line)
                if amount_match:
                    detail_fragment = normalize_spaces(line[: amount_match.start()])
                    if detail_fragment:
                        pending.detail_parts.append(detail_fragment)
                    append_transaction(
                        Decimal(amount_match.group("amount").replace(",", "")),
                        bool(amount_match.group("negative")),
                    )
                    continue
                if not normalized.startswith(("american express", "rica i zuniga", "account ending")):
                    pending.detail_parts.append(line)

        finalize()
        return ParseResult(transactions=transactions)
