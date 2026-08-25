from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class AttentionFolderPathItem(BaseModel):
    id: int
    name: str


class AttentionItemResponse(BaseModel):
    attention_id: str
    attention_type: str
    severity: str
    title: str
    description: str
    file_id: int | None
    file_name: str | None
    statement_id: int | None
    statement_label: str | None
    transaction_id: int | None
    transaction_date: date | None
    transaction_name: str | None
    transaction_amount: Decimal | None
    target_section: str
    target_field: str | None
    blocking: bool
    created_from_state: str
    folder_path: list[AttentionFolderPathItem]

    class Config:
        json_encoders = {Decimal: lambda value: f"{value:.2f}"}


class AttentionListResponse(BaseModel):
    total: int
    blocking_total: int
    review_total: int
    ready_for_summary: bool
    items: list[AttentionItemResponse]


class AttentionCountResponse(BaseModel):
    total: int
    blocking_total: int
    review_total: int
    ready_for_summary: bool
