from __future__ import annotations

from app.services.statement_detection.base import (
    ACCOUNT_PAYMENT_ACCOUNT,
    DOCUMENT_PAYMENT_ACCOUNT_STATEMENT,
    INSTITUTION_PAYPAL,
    STATUS_DETECTED,
    DetectionResult,
)
from app.services.statement_detection.common import count_present, header_text, normalize_text


def detect(text: str, filename: str = "") -> DetectionResult | None:
    normalized = normalize_text(text)
    header = header_text(text)

    issuer_signals = count_present(header, ["paypal", "paypal account", "paypal activity"])
    statement_signals = count_present(
        normalized,
        ["activity statement", "account statement", "transaction activity", "paypal balance", "statement period"],
    )

    if issuer_signals == 0 or statement_signals == 0:
        return None

    score = 0.36 + min(0.32, issuer_signals * 0.11) + min(0.24, statement_signals * 0.06)
    if "paypal" in filename.lower():
        score += 0.02

    return DetectionResult(
        document_type=DOCUMENT_PAYMENT_ACCOUNT_STATEMENT,
        institution=INSTITUTION_PAYPAL,
        account_type=ACCOUNT_PAYMENT_ACCOUNT,
        confidence=min(score, 0.96),
        status=STATUS_DETECTED,
    )
