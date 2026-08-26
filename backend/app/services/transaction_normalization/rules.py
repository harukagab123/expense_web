from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.transaction_normalization.base import NormalizationResult, SOURCE_RULE, STATUS_NEEDS_REVIEW, STATUS_NORMALIZED
from app.services.transaction_normalization.text import merchant_title, normalized_for_match


@dataclass(frozen=True)
class MerchantPattern:
    pattern: re.Pattern[str]
    normalized_name: str
    confidence: float = 0.95


KNOWN_MERCHANT_PATTERNS: tuple[MerchantPattern, ...] = (
    MerchantPattern(re.compile(r"\bTJX\s+REW(?:ARDS)?\s+M(?:STRCRD|ASTERCARD)\b"), "TJX Rewards Mastercard", 0.98),
    MerchantPattern(re.compile(r"\bCOSTCO\s+GAS\b"), "Costco Gas", 0.99),
    MerchantPattern(re.compile(r"\bCOSTCO\s+(?:WHSE|WHOLESALE|#|\d|\b)"), "Costco", 0.97),
    MerchantPattern(re.compile(r"\bAMAZON\s+MARKETPLACE\b"), "Amazon Marketplace", 0.98),
    MerchantPattern(re.compile(r"\b(?:AMZN\s+MKTPL|AMAZON\s+MKTPLACE|AMAZON\.COM|AMZN\.COM/BILL|AMAZON\s+MKTPLACE\s+PMTS)\b"), "Amazon", 0.98),
    MerchantPattern(re.compile(r"\bCHEVRON\b"), "Chevron", 0.99),
    MerchantPattern(re.compile(r"\bSHELL(?:\s+OIL)?\b"), "Shell", 0.98),
    MerchantPattern(re.compile(r"(^|\s)ARCO(\s|$)"), "ARCO", 0.96),
    MerchantPattern(re.compile(r"(^|\s)76(\s|$)"), "76", 0.95),
    MerchantPattern(re.compile(r"\bSTARBUCKS\b"), "Starbucks", 0.98),
    MerchantPattern(re.compile(r"\bCOMCAST\b"), "Comcast", 0.95),
    MerchantPattern(re.compile(r"\bAT&T\b|\bATT\b"), "AT&T", 0.95),
    MerchantPattern(re.compile(r"\bPG&E\b|\bPGE\b|\bPACIFIC\s+GAS\s+(?:AND|&)\s+ELECTRIC\b"), "PG&E", 0.96),
    MerchantPattern(re.compile(r"\bADOBE\b"), "Adobe", 0.95),
    MerchantPattern(re.compile(r"\bMICROSOFT\b|\bMSFT\b"), "Microsoft", 0.95),
    MerchantPattern(re.compile(r"\bGOOGLE\b|\bGOOG\b"), "Google", 0.95),
    MerchantPattern(re.compile(r"\bOFFICE\s*DEPOT\b|\bOFFICEDEPOT\b"), "Office Depot", 0.96),
    MerchantPattern(re.compile(r"\bSTAPLES\b"), "Staples", 0.95),
    MerchantPattern(re.compile(r"\bCAPITAL\s+ONE\s+(?:MOBILE\s+)?PMT\b|\bCAPITAL\s+ONE\b"), "Capital One", 0.93),
    MerchantPattern(re.compile(r"\bAMERICAN\s+EXPRESS\s+(?:ACH\s+)?(?:PMT|PAYMENT)\b|\bAMERICAN\s+EXPRESS\b"), "American Express", 0.93),
    MerchantPattern(re.compile(r"\bCHASE\s+(?:CARD\s+)?PMT\b|\bPAYMENT\s+TO\s+CHASE\s+CARD\b"), "Chase", 0.9),
)


PROCESSOR_PREFIX_RE = re.compile(r"^(?P<processor>PAYPAL|SQ|TST|SP)\s+(?P<merchant>[A-Z0-9][A-Z0-9 '&.-]{2,})$")
ZELLE_TO_RE = re.compile(r"^ZELLE\s+(?:PAYMENT\s+)?TO\s+(?P<name>[A-Z][A-Z '\-]*[A-Z])(?:\s+[A-Z0-9]{6,})?$")
ZELLE_FROM_RE = re.compile(r"^ZELLE\s+(?:PAYMENT\s+)?FROM\s+(?P<name>[A-Z][A-Z '\-]*[A-Z])(?:\s+[A-Z0-9]{6,})?$")
CHECK_RE = re.compile(r"^CHECK\s+#?(?P<number>\d+)$")
ATM_RE = re.compile(r"^ATM\s+WITHDRAWAL\b")
MONTHLY_FEE_RE = re.compile(r"^MONTHLY\s+SERVICE\s+FEE\b")


def match_known_rule(raw_detail: str) -> NormalizationResult | None:
    normalized = normalized_for_match(raw_detail)

    processor_result = _match_processor(normalized)
    if processor_result is not None:
        return processor_result

    zelle_result = _match_person_payment(normalized)
    if zelle_result is not None:
        return zelle_result

    check_match = CHECK_RE.match(normalized)
    if check_match is not None:
        return NormalizationResult(
            normalized_name=f"Check #{check_match.group('number')}",
            confidence=0.92,
            source=SOURCE_RULE,
            status=STATUS_NORMALIZED,
        )

    if ATM_RE.match(normalized):
        return NormalizationResult(
            normalized_name="ATM Withdrawal",
            confidence=0.9,
            source=SOURCE_RULE,
            status=STATUS_NORMALIZED,
        )

    if MONTHLY_FEE_RE.match(normalized):
        return NormalizationResult(
            normalized_name="Monthly Service Fee",
            confidence=0.94,
            source=SOURCE_RULE,
            status=STATUS_NORMALIZED,
        )

    for merchant_pattern in KNOWN_MERCHANT_PATTERNS:
        if merchant_pattern.pattern.search(normalized):
            return NormalizationResult(
                normalized_name=merchant_pattern.normalized_name,
                confidence=merchant_pattern.confidence,
                source=SOURCE_RULE,
                status=STATUS_NORMALIZED,
            )
    return None


def _match_processor(normalized: str) -> NormalizationResult | None:
    match = PROCESSOR_PREFIX_RE.match(normalized)
    if match is None:
        if normalized in {"PAYPAL PAYMENT", "PAYPAL TRANSFER", "SQ PAYMENT", "SP PAYMENT"}:
            return NormalizationResult(None, 0.2, SOURCE_RULE, STATUS_NEEDS_REVIEW)
        return None

    merchant = _clean_processor_merchant(match.group("merchant"))
    if merchant is None:
        return NormalizationResult(None, 0.24, SOURCE_RULE, STATUS_NEEDS_REVIEW)
    return NormalizationResult(merchant, 0.91, SOURCE_RULE, STATUS_NORMALIZED)


def _match_person_payment(normalized: str) -> NormalizationResult | None:
    match = ZELLE_TO_RE.match(normalized) or ZELLE_FROM_RE.match(normalized)
    if match is None:
        return None
    return NormalizationResult(
        normalized_name=merchant_title(match.group("name")),
        confidence=0.86,
        source=SOURCE_RULE,
        status=STATUS_NORMALIZED,
    )


def _clean_processor_merchant(value: str) -> str | None:
    merchant = re.sub(r"\s+\d{3,}.*$", "", value.strip())
    merchant = merchant.replace("OFFICEDEPOT", "OFFICE DEPOT")
    merchant = re.sub(r"[^A-Z0-9 '&.-]+", " ", merchant)
    merchant = re.sub(r"\s+", " ", merchant).strip(" .-*")
    if not merchant or merchant in {"PAYMENT", "TRANSFER", "PAYPAL", "SQ", "TST", "SP"}:
        return None
    if merchant == "JOES COFFEE":
        return "Joe's Coffee"
    known = match_known_rule(merchant)
    if known is not None and known.normalized_name:
        return known.normalized_name
    return merchant_title(merchant)
