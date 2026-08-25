from __future__ import annotations

from app.services.statement_detection.base import (
    ACCOUNT_CHECKING,
    ACCOUNT_CREDIT_CARD,
    DOCUMENT_BANK_STATEMENT,
    DOCUMENT_CREDIT_CARD_STATEMENT,
    INSTITUTION_CHASE,
    STATUS_DETECTED,
    DetectionResult,
)
from app.services.statement_detection.common import count_present, header_text, infer_account_type, normalize_text, product_from_text


def detect(text: str, filename: str = "") -> DetectionResult | None:
    normalized = normalize_text(text)
    header = header_text(text)
    product_name = product_from_text(header)
    if product_name and not product_name.lower().startswith("amazon"):
        product_name = None

    issuer_signals = count_present(header, ["jpmorgan chase", "chase bank", "chase.com", "chase credit card"])
    chase_header = "chase" in header
    statement_signals = count_present(
        normalized,
        [
            "transaction detail",
            "beginning balance",
            "ending balance",
            "deposits and additions",
            "withdrawals and deductions",
            "payment to chase card",
            "statement period",
            "account summary",
        ],
    )

    if issuer_signals == 0 and not chase_header:
        return None
    if issuer_signals == 0 and statement_signals < 2:
        return None

    account_type = infer_account_type(normalized, ACCOUNT_CHECKING)
    document_type = DOCUMENT_BANK_STATEMENT
    if account_type == ACCOUNT_CREDIT_CARD or "new balance" in normalized or "minimum payment" in normalized:
        account_type = ACCOUNT_CREDIT_CARD
        document_type = DOCUMENT_CREDIT_CARD_STATEMENT

    score = 0.34 + min(0.34, issuer_signals * 0.12) + min(0.24, statement_signals * 0.04)
    if product_name:
        score += 0.04
    if "chase" in filename.lower():
        score += 0.02

    return DetectionResult(
        document_type=document_type,
        institution=INSTITUTION_CHASE,
        product_name=product_name,
        account_type=account_type,
        confidence=min(score, 0.98),
        status=STATUS_DETECTED,
    )
