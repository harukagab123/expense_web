from __future__ import annotations

from dataclasses import dataclass
from datetime import date


DOCUMENT_BANK_STATEMENT = "BANK_STATEMENT"
DOCUMENT_CREDIT_CARD_STATEMENT = "CREDIT_CARD_STATEMENT"
DOCUMENT_PAYMENT_ACCOUNT_STATEMENT = "PAYMENT_ACCOUNT_STATEMENT"
DOCUMENT_OTHER_DOCUMENT = "OTHER_DOCUMENT"
DOCUMENT_UNKNOWN = "UNKNOWN"

INSTITUTION_CHASE = "CHASE"
INSTITUTION_CAPITAL_ONE = "CAPITAL_ONE"
INSTITUTION_AMEX = "AMEX"
INSTITUTION_PAYPAL = "PAYPAL"
INSTITUTION_CITI = "CITI"
INSTITUTION_TJX = "TJX"
INSTITUTION_AMAZON = "AMAZON"
INSTITUTION_OTHER_BANK = "OTHER_BANK"
INSTITUTION_UNKNOWN = "UNKNOWN"

ACCOUNT_CHECKING = "CHECKING"
ACCOUNT_SAVINGS = "SAVINGS"
ACCOUNT_CREDIT_CARD = "CREDIT_CARD"
ACCOUNT_PAYMENT_ACCOUNT = "PAYMENT_ACCOUNT"
ACCOUNT_OTHER = "OTHER"
ACCOUNT_UNKNOWN = "UNKNOWN"

STATUS_DETECTED = "DETECTED"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_NOT_A_STATEMENT = "NOT_A_STATEMENT"
STATUS_FAILED = "FAILED"
STATUS_ANALYZING = "ANALYZING"
STATUS_NOT_ANALYZED = "NOT_ANALYZED"


@dataclass(frozen=True)
class DetectionResult:
    document_type: str = DOCUMENT_UNKNOWN
    institution: str = INSTITUTION_UNKNOWN
    product_name: str | None = None
    account_type: str = ACCOUNT_UNKNOWN
    account_last_four: str | None = None
    statement_start_date: date | None = None
    statement_end_date: date | None = None
    confidence: float = 0.0
    status: str = STATUS_NEEDS_REVIEW
    reason: str | None = None

    def with_common_metadata(
        self,
        *,
        account_last_four: str | None,
        statement_start_date: date | None,
        statement_end_date: date | None,
    ) -> DetectionResult:
        return DetectionResult(
            document_type=self.document_type,
            institution=self.institution,
            product_name=self.product_name,
            account_type=self.account_type,
            account_last_four=account_last_four,
            statement_start_date=statement_start_date,
            statement_end_date=statement_end_date,
            confidence=max(0.0, min(1.0, self.confidence)),
            status=self.status,
            reason=self.reason,
        )
