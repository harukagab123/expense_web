from __future__ import annotations

from app.services.statement_detection.base import (
    ACCOUNT_CREDIT_CARD,
    DOCUMENT_CREDIT_CARD_STATEMENT,
    INSTITUTION_AMEX,
    STATUS_DETECTED,
    DetectionResult,
)
from app.services.statement_detection.common import count_present, header_text, normalize_text


def detect(text: str, filename: str = "") -> DetectionResult | None:
    normalized = normalize_text(text)
    header = header_text(text)

    issuer_signals = count_present(header, ["american express", "americanexpress.com", "amex"])
    statement_signals = count_present(
        header,
        ["statement period", "closing date", "payment due", "minimum payment due", "new balance"],
    ) + count_present(normalized, ["cardmember", "membership rewards"])

    if issuer_signals == 0:
        return None
    if "american express" not in header and statement_signals < 2:
        return None

    score = 0.35 + min(0.34, issuer_signals * 0.13) + min(0.22, statement_signals * 0.055)
    if "amex" in filename.lower() or "american" in filename.lower():
        score += 0.02

    return DetectionResult(
        document_type=DOCUMENT_CREDIT_CARD_STATEMENT,
        institution=INSTITUTION_AMEX,
        account_type=ACCOUNT_CREDIT_CARD,
        confidence=min(score, 0.96),
        status=STATUS_DETECTED,
    )
