from __future__ import annotations

from app.services.statement_detection.base import (
    ACCOUNT_CREDIT_CARD,
    DOCUMENT_CREDIT_CARD_STATEMENT,
    INSTITUTION_AMAZON,
    INSTITUTION_CHASE,
    INSTITUTION_OTHER_BANK,
    STATUS_DETECTED,
    DetectionResult,
)
from app.services.statement_detection.common import count_present, header_text, normalize_text, product_from_text


def detect(text: str, filename: str = "") -> DetectionResult | None:
    normalized = normalize_text(text)
    header = header_text(text)
    product_name = product_from_text(header)

    brand_signals = count_present(header, ["amazon store card", "amazon visa", "prime visa", "amazon credit"])
    statement_signals = count_present(header, ["statement period", "payment due", "minimum payment", "new balance", "account summary"])
    if brand_signals == 0 or statement_signals == 0:
        return None

    if "chase" in header or "jpmorgan chase" in header:
        institution = INSTITUTION_CHASE
        product_name = product_name or "Amazon Visa"
    elif "synchrony" in header:
        institution = INSTITUTION_OTHER_BANK
        product_name = product_name or "Amazon Store Card"
    else:
        institution = INSTITUTION_AMAZON
        product_name = product_name or "Amazon Credit"

    score = 0.36 + min(0.28, brand_signals * 0.1) + min(0.18, statement_signals * 0.045)
    if "amazon" in filename.lower():
        score += 0.02

    return DetectionResult(
        document_type=DOCUMENT_CREDIT_CARD_STATEMENT,
        institution=institution,
        product_name=product_name,
        account_type=ACCOUNT_CREDIT_CARD,
        confidence=min(score, 0.93),
        status=STATUS_DETECTED,
    )
