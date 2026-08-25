from __future__ import annotations

from datetime import date
import re

from app.services.statement_detection.base import (
    ACCOUNT_CHECKING,
    ACCOUNT_CREDIT_CARD,
    DOCUMENT_BANK_STATEMENT,
    DOCUMENT_CREDIT_CARD_STATEMENT,
    INSTITUTION_CITI,
    STATUS_DETECTED,
    DetectionResult,
)
from app.services.statement_detection.common import MONTHS, count_present, header_text, normalize_text


_CHECKING_PERIOD_RE = re.compile(
    r"statement\s+period\s*-?\s*(?P<start>[A-Za-z]+\s+\d{1,2})\s*-\s*"
    r"(?P<end>[A-Za-z]+\s+\d{1,2},\s*\d{4})",
    re.IGNORECASE,
)
_CARD_PERIOD_RE = re.compile(
    r"billing\s+period\s*:\s*(?P<start>\d{2}/\d{2}/\d{2,4})\s*-\s*"
    r"(?P<end>\d{2}/\d{2}/\d{2,4})",
    re.IGNORECASE,
)
_ACCOUNT_RE = re.compile(
    r"account\s+(?:number\s+)?(?:ending\s+in\s*:?\s*)?(?P<value>\d{4,})",
    re.IGNORECASE,
)


def detect(text: str, filename: str = "") -> DetectionResult | None:
    normalized = normalize_text(text)
    header = header_text(text)
    issuer_signals = count_present(header, ["citibank", "citicards", "card by citi"])
    if issuer_signals == 0:
        return None

    is_credit_card = any(
        phrase in normalized
        for phrase in ("costco anywhere visa", "minimum payment due", "cardholder summary")
    )
    is_checking = "checking activity" in normalized or "simplified banking account statement" in normalized
    if not is_credit_card and not is_checking:
        return None

    account_type = ACCOUNT_CREDIT_CARD if is_credit_card else ACCOUNT_CHECKING
    document_type = DOCUMENT_CREDIT_CARD_STATEMENT if is_credit_card else DOCUMENT_BANK_STATEMENT
    start_date, end_date = _extract_period(text, is_credit_card)
    account_last_four = _extract_account_last_four(text)
    score = 0.46 + min(0.27, issuer_signals * 0.14)
    score += 0.16 if is_credit_card or is_checking else 0.0
    if "citi" in filename.lower():
        score += 0.02

    return DetectionResult(
        document_type=document_type,
        institution=INSTITUTION_CITI,
        product_name="Costco Anywhere Visa" if "costco anywhere visa" in normalized else "Citibank Checking",
        account_type=account_type,
        account_last_four=account_last_four,
        statement_start_date=start_date,
        statement_end_date=end_date,
        confidence=min(score, 0.96),
        status=STATUS_DETECTED,
    )


def _extract_period(text: str, is_credit_card: bool) -> tuple[date | None, date | None]:
    if is_credit_card:
        match = _CARD_PERIOD_RE.search(text)
        if match is None:
            return None, None
        return _numeric_date(match.group("start")), _numeric_date(match.group("end"))

    match = _CHECKING_PERIOD_RE.search(text)
    if match is None:
        return None, None
    end_date = _word_date(match.group("end"))
    if end_date is None:
        return None, None
    start_parts = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2})", match.group("start").strip())
    if start_parts is None:
        return None, end_date
    month = _month_number(start_parts.group(1))
    if month is None:
        return None, end_date
    year = end_date.year - int(month > end_date.month)
    try:
        return date(year, month, int(start_parts.group(2))), end_date
    except ValueError:
        return None, end_date


def _numeric_date(value: str) -> date | None:
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{2,4})", value.strip())
    if match is None:
        return None
    month, day, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _word_date(value: str) -> date | None:
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", value.strip())
    if match is None:
        return None
    month = _month_number(match.group(1))
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2)))
    except ValueError:
        return None


def _extract_account_last_four(text: str) -> str | None:
    match = _ACCOUNT_RE.search(text)
    if match is None:
        return None
    return match.group("value")[-4:]


def _month_number(value: str) -> int | None:
    normalized = value.casefold()
    return MONTHS.get(normalized) or {name[:3]: number for name, number in MONTHS.items()}.get(normalized[:3])
