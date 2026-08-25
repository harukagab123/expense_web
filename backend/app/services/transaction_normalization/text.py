from __future__ import annotations

import re
import unicodedata


GENERIC_UNRESOLVED_PATTERNS = (
    re.compile(r"^(?:DBT\s+CRD|PAYMENT|ACH|DEBIT|CREDIT)\s+\d+$"),
    re.compile(r"^(?:PAYMENT|TRANSFER|ONLINE\s+TRANSFER)$"),
)

US_STATE_CODES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "IA",
    "ID",
    "IL",
    "IN",
    "KS",
    "KY",
    "LA",
    "MA",
    "MD",
    "ME",
    "MI",
    "MN",
    "MO",
    "MS",
    "MT",
    "NC",
    "ND",
    "NE",
    "NH",
    "NJ",
    "NM",
    "NV",
    "NY",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VA",
    "VT",
    "WA",
    "WI",
    "WV",
    "WY",
}

TITLE_OVERRIDES = {
    "ARCO": "ARCO",
    "AT&T": "AT&T",
    "PG&E": "PG&E",
    "TJX": "TJX",
    "AMZN": "AMZN",
    "USA": "USA",
}


def clean_description(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[*_]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalized_for_match(value: str) -> str:
    text = clean_description(value).upper()
    text = text.replace("&AMP;", "&")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def looks_unresolved(value: str) -> bool:
    normalized = normalized_for_match(value)
    return any(pattern.match(normalized) for pattern in GENERIC_UNRESOLVED_PATTERNS)


def conservative_cleanup(value: str) -> str | None:
    normalized = normalized_for_match(value)
    if looks_unresolved(normalized):
        return None

    tokens = normalized.split()
    while tokens and _is_noise_token(tokens[-1]):
        tokens.pop()
    while tokens and _is_location_state_suffix(tokens):
        tokens.pop()
        if tokens:
            tokens.pop()

    compact = " ".join(tokens)
    compact = re.sub(r"\s+#?\d{3,}\b.*$", "", compact)
    compact = re.sub(r"\b(?:STORE|STOR|TERM|AUTH|REF|ID|POS)\s+\d+\b.*$", "", compact)
    compact = re.sub(r"\s+", " ", compact).strip(" .-")

    if not compact or looks_unresolved(compact):
        return None
    if len(re.sub(r"[^A-Z]", "", compact)) < 3:
        return None
    return merchant_title(compact)


def merchant_title(value: str) -> str:
    words: list[str] = []
    for word in re.split(r"\s+", clean_description(value)):
        if not word:
            continue
        upper = word.upper()
        if upper in TITLE_OVERRIDES:
            words.append(TITLE_OVERRIDES[upper])
        elif "'" in word:
            pieces = [piece.capitalize() for piece in word.lower().split("'")]
            words.append("'".join(pieces))
        elif "&" in word:
            words.append("&".join(piece.upper() if len(piece) == 1 else piece.capitalize() for piece in word.split("&")))
        else:
            words.append(word.lower().capitalize())
    return " ".join(words)


def derive_safe_rule_pattern(raw_detail: str) -> tuple[str, str]:
    normalized = normalized_for_match(raw_detail)
    pattern = re.sub(r"\s+#?\d{3,}.*$", "", normalized)
    pattern = re.sub(r"\b(?:STORE|TERM|AUTH|REF|ID|POS)\s+\d+\b.*$", "", pattern)
    pattern = pattern.strip(" .-")
    if pattern and len(pattern) >= 4 and not looks_unresolved(pattern):
        return pattern, "PREFIX"
    return normalized, "EXACT"


def _is_noise_token(value: str) -> bool:
    return bool(re.fullmatch(r"#?\d{3,}|[A-Z0-9]{8,}|[A-Z]{2}\d{3,}", value)) or value in US_STATE_CODES


def _is_location_state_suffix(tokens: list[str]) -> bool:
    if len(tokens) < 2:
        return False
    return tokens[-1] in US_STATE_CODES and bool(re.fullmatch(r"[A-Z][A-Z.-]+", tokens[-2]))
