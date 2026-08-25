from __future__ import annotations

from app.services.statement_detection.base import (
    ACCOUNT_CREDIT_CARD,
    DOCUMENT_CREDIT_CARD_STATEMENT,
    INSTITUTION_TJX,
    STATUS_DETECTED,
    STATUS_NEEDS_REVIEW,
    DetectionResult,
)
from app.services.statement_detection.common import count_present, header_text, normalize_text, product_from_text


def detect(text: str, filename: str = "") -> DetectionResult | None:
    normalized = normalize_text(text)
    header = header_text(text)
    product_name = product_from_text(header) or "TJX Rewards"

    brand_signals = count_present(header, ["tjx rewards", "tj maxx", "marshalls", "homegoods"])
    issuer_signals = count_present(header, ["synchrony", "synchrony bank", "tjx rewards mastercard"])
    statement_signals = count_present(
        header,
        ["statement period", "payment due", "minimum payment", "new balance", "account summary"],
    ) + count_present(normalized, ["rewards platinum mastercard"])

    if brand_signals == 0:
        return None
    if statement_signals == 0:
        if "tjx rewards summary" not in normalized:
            return None
        return DetectionResult(
            document_type=DOCUMENT_CREDIT_CARD_STATEMENT,
            institution=INSTITUTION_TJX,
            product_name=product_name,
            account_type=ACCOUNT_CREDIT_CARD,
            confidence=0.64,
            status=STATUS_NEEDS_REVIEW,
            reason="The TJX PDF exposes a statement summary but no machine-readable line-item activity.",
        )

    score = 0.32 + min(0.28, brand_signals * 0.12) + min(0.22, issuer_signals * 0.08) + min(0.16, statement_signals * 0.04)
    if "tjx" in filename.lower() or "tj maxx" in filename.lower():
        score += 0.02

    return DetectionResult(
        document_type=DOCUMENT_CREDIT_CARD_STATEMENT,
        institution=INSTITUTION_TJX,
        product_name=product_name,
        account_type=ACCOUNT_CREDIT_CARD,
        confidence=min(score, 0.95),
        status=STATUS_DETECTED,
    )
