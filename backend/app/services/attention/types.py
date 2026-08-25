from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


SEVERITY_ERROR = "ERROR"
SEVERITY_REVIEW = "REVIEW"
SEVERITY_INFO = "INFO"

SECTION_STATEMENT = "statement"
SECTION_TRANSACTION = "transaction"


@dataclass(frozen=True)
class AttentionFolderPathItem:
    id: int
    name: str


@dataclass(frozen=True)
class AttentionItem:
    attention_id: str
    attention_type: str
    severity: str
    title: str
    description: str
    file_id: int | None = None
    file_name: str | None = None
    statement_id: int | None = None
    statement_label: str | None = None
    transaction_id: int | None = None
    transaction_date: date | None = None
    transaction_name: str | None = None
    transaction_amount: Decimal | None = None
    target_section: str = SECTION_TRANSACTION
    target_field: str | None = None
    blocking: bool = False
    created_from_state: str = ""
    folder_path: list[AttentionFolderPathItem] = field(default_factory=list)
