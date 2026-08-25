from __future__ import annotations

from dataclasses import dataclass


MAIN_AUTO_EXPENSE = "AUTO_EXPENSE"
MAIN_BUSINESS_USE_HOME = "BUSINESS_USE_OF_HOME"
MAIN_PROFIT_LOSS_BUSINESS = "PROFIT_LOSS_BUSINESS"
MAIN_PERSONAL_INTERNAL = "PERSONAL_INTERNAL"

AUTO_GAS = "AUTO_GAS"
AUTO_INSURANCE = "AUTO_INSURANCE"
AUTO_MAINTENANCE = "AUTO_MAINTENANCE"
AUTO_PARKING = "AUTO_PARKING"
AUTO_TIRES = "AUTO_TIRES"
AUTO_TOLLS = "AUTO_TOLLS"
AUTO_CAR_PAYMENT = "AUTO_CAR_PAYMENT"

HOME_INSURANCE = "HOME_INSURANCE"
HOME_RENT = "HOME_RENT"
HOME_REPAIRS_MAINTENANCE = "HOME_REPAIRS_MAINTENANCE"
HOME_UTILITIES = "HOME_UTILITIES"
HOME_TELECOM_INTERNET = "HOME_TELECOM_INTERNET"
HOME_OTHER_EXPENSE = "HOME_OTHER_EXPENSE"

BUSINESS_MATERIALS = "BUSINESS_MATERIALS"
BUSINESS_ADVERTISING = "BUSINESS_ADVERTISING"
BUSINESS_INTEREST_OTHER = "BUSINESS_INTEREST_OTHER"
BUSINESS_LEGAL_PROFESSIONAL = "BUSINESS_LEGAL_PROFESSIONAL"
BUSINESS_OFFICE_EXPENSE = "BUSINESS_OFFICE_EXPENSE"
BUSINESS_OTHER_SUPPLIES = "BUSINESS_OTHER_SUPPLIES"
BUSINESS_TRAVEL = "BUSINESS_TRAVEL"
BUSINESS_TOTAL_MEALS = "BUSINESS_TOTAL_MEALS"
BUSINESS_TRANSPORTATION = "BUSINESS_TRANSPORTATION"
BUSINESS_GOVERNMENT = "BUSINESS_GOVERNMENT"
BUSINESS_DONATIONS = "BUSINESS_DONATIONS"
BUSINESS_BANK_MEMBERSHIP = "BUSINESS_BANK_MEMBERSHIP"
BUSINESS_MEDICAL = "BUSINESS_MEDICAL"
BUSINESS_EDUCATION_LEARNING = "BUSINESS_EDUCATION_LEARNING"

PERSONAL_OTHER_ITEMS = "PERSONAL_OTHER_ITEMS"
PERSONAL = "PERSONAL"
UNCATEGORIZED = "UNCATEGORIZED"

SOURCE_RULE = "RULE"
SOURCE_MERCHANT_RULE = "MERCHANT_RULE"
SOURCE_USER_EDITED = "USER_EDITED"
SOURCE_LEARNED_RULE = "LEARNED_RULE"
SOURCE_UNRESOLVED = "UNRESOLVED"

STATUS_NOT_CATEGORIZED = "NOT_CATEGORIZED"
STATUS_CATEGORIZED = "CATEGORIZED"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_USER_CONFIRMED = "USER_CONFIRMED"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

MATCH_EXACT = "EXACT"
MATCH_PREFIX = "PREFIX"
MATCH_CONTAINS = "CONTAINS"
MATCH_REGEX = "REGEX"
MATCH_NORMALIZED_NAME = "NORMALIZED_NAME"

ELIGIBLE_TRANSACTION_TYPES = {"EXPENSE", "BANK_FEE", "INTEREST"}


@dataclass(frozen=True)
class SubcategoryDefinition:
    id: str
    label: str


@dataclass(frozen=True)
class MainCategoryDefinition:
    id: str
    label: str
    subcategories: tuple[SubcategoryDefinition, ...]


CATEGORY_CATALOG: tuple[MainCategoryDefinition, ...] = (
    MainCategoryDefinition(
        MAIN_AUTO_EXPENSE,
        "AUTO EXPENSE",
        (
            SubcategoryDefinition(AUTO_GAS, "Gas"),
            SubcategoryDefinition(AUTO_INSURANCE, "Insurance"),
            SubcategoryDefinition(AUTO_MAINTENANCE, "Car Maintenance"),
            SubcategoryDefinition(AUTO_PARKING, "Parking Fee"),
            SubcategoryDefinition(AUTO_TIRES, "Tires"),
            SubcategoryDefinition(AUTO_TOLLS, "Tolls"),
            SubcategoryDefinition(AUTO_CAR_PAYMENT, "Car Payment"),
        ),
    ),
    MainCategoryDefinition(
        MAIN_BUSINESS_USE_HOME,
        "BUSINESS USE OF HOME",
        (
            SubcategoryDefinition(HOME_INSURANCE, "Insurance"),
            SubcategoryDefinition(HOME_RENT, "Rent"),
            SubcategoryDefinition(HOME_REPAIRS_MAINTENANCE, "Repairs and Maintenance"),
            SubcategoryDefinition(HOME_UTILITIES, "Utilities"),
            SubcategoryDefinition(HOME_TELECOM_INTERNET, "Telecom/Internet"),
            SubcategoryDefinition(HOME_OTHER_EXPENSE, "Other Expense"),
        ),
    ),
    MainCategoryDefinition(
        MAIN_PROFIT_LOSS_BUSINESS,
        "PROFIT OR LOSS FROM BUSINESS",
        (
            SubcategoryDefinition(BUSINESS_MATERIALS, "Materials"),
            SubcategoryDefinition(BUSINESS_ADVERTISING, "Advertising"),
            SubcategoryDefinition(BUSINESS_INTEREST_OTHER, "Interest - Other"),
            SubcategoryDefinition(BUSINESS_LEGAL_PROFESSIONAL, "Legal and Professional Services"),
            SubcategoryDefinition(BUSINESS_OFFICE_EXPENSE, "Office Expense"),
            SubcategoryDefinition(BUSINESS_OTHER_SUPPLIES, "Other Supplies"),
            SubcategoryDefinition(BUSINESS_TRAVEL, "Travel"),
            SubcategoryDefinition(BUSINESS_TOTAL_MEALS, "Total Meals"),
            SubcategoryDefinition(BUSINESS_TRANSPORTATION, "Transportation"),
            SubcategoryDefinition(BUSINESS_GOVERNMENT, "Government"),
            SubcategoryDefinition(BUSINESS_DONATIONS, "Donations"),
            SubcategoryDefinition(BUSINESS_BANK_MEMBERSHIP, "Bank Membership"),
            SubcategoryDefinition(BUSINESS_MEDICAL, "Medical"),
            SubcategoryDefinition(BUSINESS_EDUCATION_LEARNING, "Education & Learning"),
        ),
    ),
    MainCategoryDefinition(
        MAIN_PERSONAL_INTERNAL,
        "PERSONAL / INTERNAL",
        (
            SubcategoryDefinition(PERSONAL_OTHER_ITEMS, "Other Personal Items"),
            SubcategoryDefinition(PERSONAL, "Personal"),
            SubcategoryDefinition(UNCATEGORIZED, "Uncategorized"),
        ),
    ),
)

CATEGORY_IDS = {category.id for category in CATEGORY_CATALOG}
SUBCATEGORY_TO_MAIN = {
    subcategory.id: category.id
    for category in CATEGORY_CATALOG
    for subcategory in category.subcategories
}
MAIN_TO_SUBCATEGORIES = {
    category.id: {subcategory.id for subcategory in category.subcategories}
    for category in CATEGORY_CATALOG
}


@dataclass(frozen=True)
class CategoryClassificationResult:
    main_category: str | None
    subcategory: str | None
    confidence: float
    source: str
    status: str
    rule_id: int | None = None


@dataclass(frozen=True)
class CategoryClassificationInput:
    transaction_detail: str
    normalized_name: str | None
    transaction_type: str
    direction: str
    statement_institution: str
    account_type: str


@dataclass(frozen=True)
class UserCategoryRule:
    id: int
    pattern: str
    main_category: str
    subcategory: str
    match_type: str


def is_valid_category_pair(main_category: str, subcategory: str) -> bool:
    return subcategory in MAIN_TO_SUBCATEGORIES.get(main_category, set())


def main_category_for_subcategory(subcategory: str) -> str | None:
    return SUBCATEGORY_TO_MAIN.get(subcategory)


def is_category_eligible(transaction_type: str, direction: str) -> bool:
    if transaction_type == "INTEREST":
        return direction == "OUTFLOW"
    return transaction_type in ELIGIBLE_TRANSACTION_TYPES


def uncategorized_result(confidence: float = 0.35) -> CategoryClassificationResult:
    return CategoryClassificationResult(
        main_category=MAIN_PERSONAL_INTERNAL,
        subcategory=UNCATEGORIZED,
        confidence=confidence,
        source=SOURCE_UNRESOLVED,
        status=STATUS_NEEDS_REVIEW,
    )


def not_applicable_result() -> CategoryClassificationResult:
    return CategoryClassificationResult(
        main_category=None,
        subcategory=None,
        confidence=1.0,
        source=SOURCE_UNRESOLVED,
        status=STATUS_NOT_APPLICABLE,
    )


def categorized_result(
    main_category: str,
    subcategory: str,
    confidence: float,
    *,
    source: str = SOURCE_RULE,
    status: str | None = None,
    rule_id: int | None = None,
) -> CategoryClassificationResult:
    return CategoryClassificationResult(
        main_category=main_category,
        subcategory=subcategory,
        confidence=confidence,
        source=source,
        status=status or (STATUS_CATEGORIZED if confidence >= 0.7 else STATUS_NEEDS_REVIEW),
        rule_id=rule_id,
    )
