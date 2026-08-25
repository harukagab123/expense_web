from __future__ import annotations

from datetime import date
import re

from app.services.statement_detection.base import (
    ACCOUNT_CREDIT_CARD,
    DOCUMENT_BANK_STATEMENT,
    DOCUMENT_CREDIT_CARD_STATEMENT,
    INSTITUTION_CAPITAL_ONE,
    STATUS_DETECTED,
    DetectionResult,
)
from app.services.statement_detection.common import MONTHS, count_present, header_text, infer_account_type, normalize_text


_PERIOD_RE = re.compile(
    r"(?:statement\s+period\s*)?(?P<start>[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})\s*"
    r"(?:-|to|through|thru|\u2013|\u2014)\s*(?P<end>[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})",
    re.IGNORECASE,
)


def detect(text: str, filename: str = "") -> DetectionResult | None:
    normalized = normalize_text(text)
    header = header_text(text)

    issuer_signals = count_present(header, ["capital one bank", "capital one, n.a.", "capital one"])
    statement_signals = count_present(
        header,
        ["statement period", "account summary", "payment due", "minimum payment", "new balance"],
    ) + count_present(normalized, ["capital one online", "capitalone.com"])

    if issuer_signals == 0:
        return None
    if "capital one" not in header and statement_signals < 2:
        return None

    is_credit_card = any(
        signal in header
        for signal in ("credit card", "mastercard", "credit limit", "minimum payment", "new balance")
    )
    account_type = ACCOUNT_CREDIT_CARD if is_credit_card else infer_account_type(normalized, ACCOUNT_CREDIT_CARD)
    document_type = DOCUMENT_CREDIT_CARD_STATEMENT if account_type == ACCOUNT_CREDIT_CARD else DOCUMENT_BANK_STATEMENT
    statement_start_date, statement_end_date = _extract_period(text)
    score = 0.32 + min(0.36, issuer_signals * 0.12) + min(0.22, statement_signals * 0.055)
    if "capital" in filename.lower():
        score += 0.02

    return DetectionResult(
        document_type=document_type,
        institution=INSTITUTION_CAPITAL_ONE,
        account_type=account_type,
        statement_start_date=statement_start_date,
        statement_end_date=statement_end_date,
        confidence=min(score, 0.96),
        status=STATUS_DETECTED,
    )


def _extract_period(text: str) -> tuple[date | None, date | None]:
    match = _PERIOD_RE.search(text)
    if match is None:
        return None, None
    return _parse_word_date(match.group("start")), _parse_word_date(match.group("end"))


def _parse_word_date(value: str) -> date | None:
    match = re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})", value.strip())
    if match is None:
        return None
    month_name, day, year = match.groups()
    month = MONTHS.get(month_name.casefold()) or {name[:3]: number for name, number in MONTHS.items()}.get(
        month_name.casefold()[:3]
    )
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None
