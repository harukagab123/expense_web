from __future__ import annotations

from datetime import date, datetime
import re
from typing import Literal

from pydantic import BaseModel, Field, root_validator, validator


DocumentType = Literal[
    "BANK_STATEMENT",
    "CREDIT_CARD_STATEMENT",
    "PAYMENT_ACCOUNT_STATEMENT",
    "OTHER_DOCUMENT",
    "UNKNOWN",
]
Institution = Literal[
    "CHASE",
    "CAPITAL_ONE",
    "AMEX",
    "PAYPAL",
    "CITI",
    "TJX",
    "AMAZON",
    "OTHER_BANK",
    "UNKNOWN",
]
AccountType = Literal[
    "CHECKING",
    "SAVINGS",
    "CREDIT_CARD",
    "PAYMENT_ACCOUNT",
    "OTHER",
    "UNKNOWN",
]


class StatementResponse(BaseModel):
    id: int
    file_id: int
    document_type: str
    institution: str
    product_name: str | None
    account_type: str
    account_last_four: str | None
    statement_start_date: date | None
    statement_end_date: date | None
    detected_document_type: str | None
    detected_institution: str | None
    detected_product_name: str | None
    detected_account_type: str | None
    detected_account_last_four: str | None
    detected_statement_start_date: date | None
    detected_statement_end_date: date | None
    original_document_type: str | None
    original_institution: str | None
    original_product_name: str | None
    original_account_type: str | None
    original_account_last_four: str | None
    original_statement_start_date: date | None
    original_statement_end_date: date | None
    original_detected_at: datetime | None
    metadata_source: str
    user_corrected: bool
    manual_updated_at: datetime | None
    detection_confidence: float = Field(ge=0.0, le=1.0)
    detection_status: str
    detection_reason: str | None
    detected_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class StatementLookupResponse(BaseModel):
    statement: StatementResponse | None = None


class StatementUpdate(BaseModel):
    document_type: DocumentType | None = None
    institution: Institution | None = None
    product_name: str | None = Field(default=None, max_length=255)
    account_type: AccountType | None = None
    account_last_four: str | None = None
    statement_start_date: date | None = None
    statement_end_date: date | None = None

    @validator("product_name", pre=True)
    def clean_product_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @validator("account_last_four", pre=True)
    def clean_account_last_four(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned:
            return None
        if re.fullmatch(r"\d{1,4}", cleaned) is None:
            raise ValueError("Account last four must contain 1 to 4 digits only.")
        return cleaned

    @root_validator
    def validate_date_range(cls, values):
        start_date = values.get("statement_start_date")
        end_date = values.get("statement_end_date")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("Statement start date must be on or before statement end date.")
        return values
