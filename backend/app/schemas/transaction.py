from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Literal

from pydantic import BaseModel, Field, root_validator, validator

from app.services.transaction_categorization.base import (
    CATEGORY_CATALOG,
    CATEGORY_IDS,
    SUBCATEGORY_TO_MAIN,
    is_valid_category_pair,
)


Direction = Literal["INFLOW", "OUTFLOW", "UNKNOWN"]
NormalizationMatchType = Literal["EXACT", "PREFIX", "CONTAINS", "REGEX"]
CategoryMatchType = Literal["EXACT", "PREFIX", "CONTAINS", "REGEX", "NORMALIZED_NAME"]
ReviewStatusValue = Literal["PENDING", "NEEDS_REVIEW", "REVIEWED"]
TransactionTypeValue = Literal[
    "EXPENSE",
    "INCOME",
    "TRANSFER",
    "CREDIT_CARD_PAYMENT",
    "REFUND",
    "ATM_CASH_WITHDRAWAL",
    "CHECK",
    "BANK_FEE",
    "INTEREST",
    "OTHER",
    "UNKNOWN",
]

CategoryMainValue = Literal[
    "AUTO_EXPENSE",
    "BUSINESS_USE_OF_HOME",
    "PROFIT_LOSS_BUSINESS",
    "PERSONAL_INTERNAL",
]
CategorySubcategoryValue = Literal[
    "AUTO_GAS",
    "AUTO_INSURANCE",
    "AUTO_MAINTENANCE",
    "AUTO_PARKING",
    "AUTO_TIRES",
    "AUTO_TOLLS",
    "AUTO_CAR_PAYMENT",
    "HOME_INSURANCE",
    "HOME_RENT",
    "HOME_REPAIRS_MAINTENANCE",
    "HOME_UTILITIES",
    "HOME_TELECOM_INTERNET",
    "HOME_OTHER_EXPENSE",
    "BUSINESS_MATERIALS",
    "BUSINESS_ADVERTISING",
    "BUSINESS_INTEREST_OTHER",
    "BUSINESS_LEGAL_PROFESSIONAL",
    "BUSINESS_OFFICE_EXPENSE",
    "BUSINESS_OTHER_SUPPLIES",
    "BUSINESS_TRAVEL",
    "BUSINESS_TOTAL_MEALS",
    "BUSINESS_TRANSPORTATION",
    "BUSINESS_GOVERNMENT",
    "BUSINESS_DONATIONS",
    "BUSINESS_BANK_MEMBERSHIP",
    "BUSINESS_MEDICAL",
    "BUSINESS_EDUCATION_LEARNING",
    "PERSONAL_OTHER_ITEMS",
    "PERSONAL",
    "UNCATEGORIZED",
]


class SubcategoryCatalogResponse(BaseModel):
    id: str
    label: str


class MainCategoryCatalogResponse(BaseModel):
    id: str
    label: str
    subcategories: list[SubcategoryCatalogResponse]


class CategoryCatalogResponse(BaseModel):
    categories: list[MainCategoryCatalogResponse]

    @classmethod
    def from_catalog(cls) -> "CategoryCatalogResponse":
        return cls(
            categories=[
                MainCategoryCatalogResponse(
                    id=category.id,
                    label=category.label,
                    subcategories=[
                        SubcategoryCatalogResponse(id=subcategory.id, label=subcategory.label)
                        for subcategory in category.subcategories
                    ],
                )
                for category in CATEGORY_CATALOG
            ],
        )


class TransactionExtractionResponse(BaseModel):
    id: int
    statement_id: int
    parser_name: str
    parser_version: str
    status: str
    transaction_count: int
    review_count: int
    message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class TransactionResponse(BaseModel):
    id: int
    statement_id: int
    extraction_id: int | None
    transaction_date: date
    transaction_detail: str
    amount: Decimal
    direction: str
    source_page: int | None
    source_order: int
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool
    user_edited: bool
    user_added: bool
    excluded: bool
    source: str
    original_transaction_date: date | None
    original_transaction_detail: str | None
    original_amount: Decimal | None
    original_direction: str | None
    original_source_page: int | None
    original_source_order: int | None
    normalized_name: str | None
    normalization_confidence: float = Field(ge=0.0, le=1.0)
    normalization_source: str
    normalization_status: str
    normalized_at: datetime | None
    original_normalized_name: str | None
    original_normalization_confidence: float | None
    original_normalization_source: str | None
    original_normalization_status: str | None
    user_edited_normalization: bool
    normalization_rule_id: int | None
    transaction_type: str
    type_confidence: float = Field(ge=0.0, le=1.0)
    type_source: str
    type_status: str
    type_updated_at: datetime | None
    suggested_include: str
    original_transaction_type: str | None
    original_type_confidence: float | None
    original_type_source: str | None
    original_type_status: str | None
    original_suggested_include: str | None
    user_edited_type: bool
    type_rule_id: int | None
    main_category: str | None
    subcategory: str | None
    category_confidence: float = Field(ge=0.0, le=1.0)
    category_source: str
    category_status: str
    category_updated_at: datetime | None
    original_main_category: str | None
    original_subcategory: str | None
    original_category_confidence: float | None
    original_category_source: str | None
    original_category_status: str | None
    user_edited_category: bool
    category_rule_id: int | None
    include_in_expenses: bool | None
    inclusion_initialized: bool
    inclusion_source: str
    inclusion_updated_at: datetime | None
    review_status: str
    review_source: str
    review_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
        json_encoders = {Decimal: lambda value: f"{value:.2f}"}


class TransactionListResponse(BaseModel):
    latest_extraction: TransactionExtractionResponse | None = None
    transactions: list[TransactionResponse]


class TransactionExtractionRunResponse(BaseModel):
    extraction: TransactionExtractionResponse
    transactions: list[TransactionResponse]


class TransactionNormalizationRunResponse(BaseModel):
    transactions: list[TransactionResponse]


class TransactionTypeClassificationRunResponse(BaseModel):
    transactions: list[TransactionResponse]


class TransactionTypeBulkUpdateResponse(BaseModel):
    transactions: list[TransactionResponse]
    skipped_transaction_ids: list[int]


class TransactionCategorizationRunResponse(BaseModel):
    transactions: list[TransactionResponse]


class TransactionCategoryBulkUpdateResponse(BaseModel):
    transactions: list[TransactionResponse]
    skipped_transaction_ids: list[int]


class TransactionInclusionBulkUpdateResponse(BaseModel):
    transactions: list[TransactionResponse]
    skipped_transaction_ids: list[int]


class TransactionReviewBulkUpdateResponse(BaseModel):
    transactions: list[TransactionResponse]
    skipped_transaction_ids: list[int]


class MerchantNormalizationRuleResponse(BaseModel):
    id: int
    pattern: str
    normalized_name: str
    match_type: str
    times_confirmed: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class TransactionTypeRuleResponse(BaseModel):
    id: int
    pattern: str
    transaction_type: str
    match_type: str
    times_confirmed: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class CategoryRuleResponse(BaseModel):
    id: int
    pattern: str
    main_category: str
    subcategory: str
    match_type: str
    times_confirmed: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class TransactionCreate(BaseModel):
    transaction_date: date
    transaction_detail: str
    amount: Decimal
    direction: Direction

    @validator("transaction_detail", pre=True)
    def clean_transaction_detail(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("Transaction detail is required.")
        return cleaned

    @validator("amount", pre=True)
    def clean_amount(cls, value: str | Decimal) -> Decimal:
        return clean_money_amount(value)


class TransactionUpdate(BaseModel):
    transaction_date: date | None = None
    transaction_detail: str | None = None
    amount: Decimal | None = None
    direction: Direction | None = None

    @validator("transaction_detail", pre=True)
    def clean_transaction_detail(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("Transaction detail is required.")
        return cleaned

    @validator("amount", pre=True)
    def clean_amount(cls, value: str | Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return clean_money_amount(value)


def clean_money_amount(value: str | Decimal) -> Decimal:
    text = str(value).strip().replace(",", "")
    if re.fullmatch(r"\d+(?:\.\d{1,2})?", text) is None:
        raise ValueError("Amount must be valid money, such as 100 or 100.00.")
    try:
        amount = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Amount must be valid money, such as 100 or 100.00.") from exc
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    return amount


class TransactionNormalizationUpdate(BaseModel):
    normalized_name: str = Field(min_length=1, max_length=255)
    use_for_future: bool = False
    match_type: NormalizationMatchType | None = None

    @validator("normalized_name", pre=True)
    def clean_normalized_name(cls, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(value)).strip()
        if not cleaned:
            raise ValueError("Normalized name is required.")
        return cleaned


class TransactionTypeUpdate(BaseModel):
    transaction_type: TransactionTypeValue
    use_for_future: bool = False
    match_type: NormalizationMatchType | None = None


class TransactionTypeBulkUpdate(BaseModel):
    transaction_ids: list[int] = Field(min_items=1)
    transaction_type: TransactionTypeValue
    overwrite_user_edits: bool = False


class TransactionCategoryUpdate(BaseModel):
    main_category: CategoryMainValue
    subcategory: CategorySubcategoryValue
    use_for_future: bool = False
    match_type: CategoryMatchType | None = None
    replace_existing_rule: bool = False

    @root_validator
    def validate_category_pair(cls, values):
        main_category = values.get("main_category")
        subcategory = values.get("subcategory")
        if main_category not in CATEGORY_IDS or subcategory not in SUBCATEGORY_TO_MAIN:
            raise ValueError("Category is not supported.")
        if not is_valid_category_pair(main_category, subcategory):
            raise ValueError("Subcategory is not valid for the selected category.")
        return values


class CategoryRuleUpdate(BaseModel):
    main_category: CategoryMainValue
    subcategory: CategorySubcategoryValue

    @root_validator
    def validate_category_pair(cls, values):
        main_category = values.get("main_category")
        subcategory = values.get("subcategory")
        if main_category not in CATEGORY_IDS or subcategory not in SUBCATEGORY_TO_MAIN:
            raise ValueError("Category is not supported.")
        if not is_valid_category_pair(main_category, subcategory):
            raise ValueError("Subcategory is not valid for the selected category.")
        return values


class TransactionCategoryBulkUpdate(BaseModel):
    transaction_ids: list[int] = Field(min_items=1)
    main_category: CategoryMainValue
    subcategory: CategorySubcategoryValue
    overwrite_user_edits: bool = False

    @root_validator
    def validate_category_pair(cls, values):
        main_category = values.get("main_category")
        subcategory = values.get("subcategory")
        if main_category not in CATEGORY_IDS or subcategory not in SUBCATEGORY_TO_MAIN:
            raise ValueError("Category is not supported.")
        if not is_valid_category_pair(main_category, subcategory):
            raise ValueError("Subcategory is not valid for the selected category.")
        return values


class TransactionInclusionUpdate(BaseModel):
    include_in_expenses: bool


class TransactionInclusionBulkUpdate(BaseModel):
    transaction_ids: list[int] = Field(min_items=1)
    include_in_expenses: bool


class TransactionReviewUpdate(BaseModel):
    review_status: ReviewStatusValue


class TransactionReviewBulkUpdate(BaseModel):
    transaction_ids: list[int] = Field(min_items=1)
    review_status: ReviewStatusValue
