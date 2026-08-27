from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class SummaryPeriodResponse(BaseModel):
    mode: str
    label: str
    start_date: date
    end_date: date
    tax_year: int | None = None
    available_years: list[int] = Field(default_factory=list)


class SummaryTransactionResponse(BaseModel):
    id: int
    statement_id: int
    file_id: int
    transaction_date: date
    normalized_name: str | None
    transaction_detail: str
    institution: str
    source_file: str
    source_file_available: bool
    transaction_type: str
    direction: str
    main_category: str | None
    main_category_label: str | None
    subcategory: str | None
    subcategory_label: str | None
    amount: str
    category_status: str
    review_status: str


class SummarySubcategoryResponse(BaseModel):
    id: str
    label: str
    priority: int
    transaction_count: int
    total: str
    transactions: list[SummaryTransactionResponse] = Field(default_factory=list)


class SummaryGroupResponse(BaseModel):
    id: str
    label: str
    transaction_count: int
    total: str
    subcategories: list[SummarySubcategoryResponse] = Field(default_factory=list)


class SummaryMetricsResponse(BaseModel):
    included_eligible_count: int
    contributing_transaction_count: int
    needs_review_count: int
    source_count: int
    not_applicable_count: int
    unselected_count: int
    other_supplies_count: int


class ExpenseSummaryResponse(BaseModel):
    period: SummaryPeriodResponse
    readiness: str
    grand_total: str
    metrics: SummaryMetricsResponse
    groups: list[SummaryGroupResponse] = Field(default_factory=list)
    needs_review_transactions: list[SummaryTransactionResponse] = Field(default_factory=list)
