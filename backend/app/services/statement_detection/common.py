from __future__ import annotations

from datetime import date
import re

from app.services.statement_detection.base import (
    ACCOUNT_CHECKING,
    ACCOUNT_CREDIT_CARD,
    ACCOUNT_PAYMENT_ACCOUNT,
    ACCOUNT_SAVINGS,
    ACCOUNT_UNKNOWN,
)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

DATE_PATTERN = (
    r"(?:\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4})"
)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def header_text(text: str, limit: int = 3000) -> str:
    return normalize_text(text[:limit])


def count_present(haystack: str, phrases: list[str]) -> int:
    return sum(1 for phrase in phrases if phrase.lower() in haystack)


def has_statement_context(normalized: str) -> bool:
    phrases = [
        "statement period",
        "account summary",
        "payment due",
        "new balance",
        "beginning balance",
        "ending balance",
        "transaction detail",
        "account number",
        "card ending",
        "account ending",
    ]
    return count_present(normalized, phrases) >= 1


def has_financial_context(normalized: str) -> bool:
    phrases = [
        "statement",
        "account",
        "payment",
        "balance",
        "credit card",
        "checking",
        "savings",
        "transaction",
    ]
    return count_present(normalized, phrases) >= 2


def infer_account_type(normalized: str, default: str = ACCOUNT_UNKNOWN) -> str:
    if "checking" in normalized:
        return ACCOUNT_CHECKING
    if "savings" in normalized:
        return ACCOUNT_SAVINGS
    if "credit card" in normalized or "minimum payment" in normalized or "payment due" in normalized:
        return ACCOUNT_CREDIT_CARD
    if "paypal account" in normalized or "payment account" in normalized:
        return ACCOUNT_PAYMENT_ACCOUNT
    return default


def extract_statement_period(text: str) -> tuple[date | None, date | None]:
    patterns = [
        rf"statement\s+period\s*:?\s*({DATE_PATTERN})\s*(?:-|to|through|thru|–|—)\s*({DATE_PATTERN})",
        rf"billing\s+period\s*:?\s*({DATE_PATTERN})\s*(?:-|to|through|thru|–|—)\s*({DATE_PATTERN})",
        rf"activity\s+period\s*:?\s*({DATE_PATTERN})\s*(?:-|to|through|thru|–|—)\s*({DATE_PATTERN})",
        rf"({DATE_PATTERN})\s*(?:-|to|through|thru|–|—)\s*({DATE_PATTERN})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        start = parse_date(match.group(1))
        end = parse_date(match.group(2))
        if start and end:
            return start, end
    return None, None


def parse_date(value: str) -> date | None:
    clean = value.strip().replace(",", "")
    numeric = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", clean)
    if numeric:
        month, day, year = (int(part) for part in numeric.groups())
        if year < 100:
            year += 2000
        return _safe_date(year, month, day)

    word = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})", clean)
    if word:
        month_name, day, year = word.groups()
        month = MONTHS.get(month_name.lower())
        if month is None:
            return None
        return _safe_date(int(year), month, int(day))

    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_account_last_four(text: str) -> str | None:
    labeled_patterns = [
        r"(?:account|acct)\s+(?:ending|ending\s+in|ends\s+in)\D{0,20}(\d{4})",
        r"(?:card|account)\s+ending\D{0,20}(\d{4})",
        r"(?:card|account)\s+number\s*:?\s*[xX*][xX*\s-]+(\d{4})\b",
    ]
    for pattern in labeled_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    full_number = re.search(
        r"(?:account|card)\s+number\s*:?\s*([xX*\d][xX*\d\s-]{6,30}\d)",
        text,
        flags=re.IGNORECASE,
    )
    if not full_number:
        return None

    digits = re.sub(r"\D", "", full_number.group(1))
    if len(digits) >= 4:
        return digits[-4:]
    return None


def product_from_text(normalized_header: str) -> str | None:
    if "amazon prime visa" in normalized_header or "prime visa" in normalized_header:
        return "Amazon Prime Visa"
    if "amazon store card" in normalized_header:
        return "Amazon Store Card"
    if "amazon visa" in normalized_header:
        return "Amazon Visa"
    if "tjx rewards platinum mastercard" in normalized_header:
        return "TJX Rewards Platinum Mastercard"
    if "tjx rewards" in normalized_header:
        return "TJX Rewards"
    return None
