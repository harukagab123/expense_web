from __future__ import annotations

from app.services.statement_detection import amazon, amex, capital_one, chase, citi, paypal, tjx
from app.services.statement_detection.base import (
    ACCOUNT_UNKNOWN,
    DOCUMENT_OTHER_DOCUMENT,
    DOCUMENT_UNKNOWN,
    INSTITUTION_UNKNOWN,
    STATUS_NEEDS_REVIEW,
    STATUS_NOT_A_STATEMENT,
    DetectionResult,
)
from app.services.statement_detection.common import (
    extract_account_last_four,
    extract_statement_period,
    has_financial_context,
    infer_account_type,
    normalize_text,
)

DETECTORS = [
    chase.detect,
    capital_one.detect,
    amex.detect,
    citi.detect,
    paypal.detect,
    tjx.detect,
    amazon.detect,
]


def detect_statement_text(text: str, filename: str = "") -> DetectionResult:
    if not text.strip():
        return DetectionResult(
            document_type=DOCUMENT_UNKNOWN,
            institution=INSTITUTION_UNKNOWN,
            account_type=ACCOUNT_UNKNOWN,
            confidence=0.2,
            status=STATUS_NEEDS_REVIEW,
            reason="No extractable PDF text found.",
        )

    candidates = [candidate for detector in DETECTORS if (candidate := detector(text, filename)) is not None]
    normalized = normalize_text(text)
    start_date, end_date = extract_statement_period(text)
    last_four = extract_account_last_four(text)

    if candidates:
        best = max(candidates, key=lambda result: result.confidence)
        return best.with_common_metadata(
            account_last_four=last_four or best.account_last_four,
            statement_start_date=start_date or best.statement_start_date,
            statement_end_date=end_date or best.statement_end_date,
        )

    if has_financial_context(normalized):
        return DetectionResult(
            document_type=DOCUMENT_UNKNOWN,
            institution=INSTITUTION_UNKNOWN,
            account_type=infer_account_type(normalized),
            account_last_four=last_four,
            statement_start_date=start_date,
            statement_end_date=end_date,
            confidence=0.35,
            status=STATUS_NEEDS_REVIEW,
            reason="The document has financial wording but no supported institution matched.",
        )

    return DetectionResult(
        document_type=DOCUMENT_OTHER_DOCUMENT,
        institution=INSTITUTION_UNKNOWN,
        account_type=ACCOUNT_UNKNOWN,
        account_last_four=last_four,
        statement_start_date=start_date,
        statement_end_date=end_date,
        confidence=0.08,
        status=STATUS_NOT_A_STATEMENT,
        reason="No statement-like financial document signals were found.",
    )
