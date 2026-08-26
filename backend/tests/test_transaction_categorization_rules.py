from app.services.transaction_categorization.base import (
    AUTO_GAS,
    BUSINESS_INTEREST_OTHER,
    BUSINESS_BANK_MEMBERSHIP,
    BUSINESS_MEDICAL,
    BUSINESS_OFFICE_EXPENSE,
    BUSINESS_TOTAL_MEALS,
    BUSINESS_TRAVEL,
    CATEGORY_CATALOG,
    HOME_TELECOM_INTERNET,
    MAIN_AUTO_EXPENSE,
    MAIN_BUSINESS_USE_HOME,
    MAIN_PROFIT_LOSS_BUSINESS,
    STATUS_CATEGORIZED,
    STATUS_NEEDS_REVIEW,
    STATUS_NOT_APPLICABLE,
    CategoryClassificationInput,
    is_valid_category_pair,
)
from app.services.transaction_categorization.engine import categorize_transaction


def categorize(
    raw_detail: str,
    transaction_type: str = "EXPENSE",
    direction: str = "OUTFLOW",
    normalized_name: str | None = None,
):
    return categorize_transaction(
        CategoryClassificationInput(
            transaction_detail=raw_detail,
            normalized_name=normalized_name,
            transaction_type=transaction_type,
            direction=direction,
            statement_institution="CHASE",
            account_type="CHECKING",
        )
    )


def test_exact_category_structure_and_valid_pairs() -> None:
    catalog = {category.id: [subcategory.label for subcategory in category.subcategories] for category in CATEGORY_CATALOG}

    assert catalog == {
        MAIN_AUTO_EXPENSE: ["Gas", "Insurance", "Car Maintenance", "Parking Fee", "Tires", "Tolls", "Car Payment"],
        MAIN_BUSINESS_USE_HOME: [
            "Insurance",
            "Rent",
            "Repairs and Maintenance",
            "Utilities",
            "Telecom/Internet",
            "Other Expense",
        ],
        MAIN_PROFIT_LOSS_BUSINESS: [
            "Materials",
            "Advertising",
            "Interest - Other",
            "Legal and Professional Services",
            "Office Expense",
            "Other Supplies",
            "Travel",
            "Total Meals",
            "Transportation",
            "Government",
            "Donations",
            "Bank Membership",
            "Medical",
            "Education & Learning",
        ],
    }
    assert is_valid_category_pair(MAIN_AUTO_EXPENSE, AUTO_GAS)
    assert not is_valid_category_pair(MAIN_AUTO_EXPENSE, BUSINESS_OFFICE_EXPENSE)


def test_gas_and_ambiguous_retail_rules() -> None:
    gas_examples = [
        categorize("CHEVRON 0094821 FREMONT CA", normalized_name="Chevron"),
        categorize("SHELL OIL 1234", normalized_name="Shell"),
        categorize("COSTCO GAS #01234", normalized_name="Costco Gas"),
    ]
    for result in gas_examples:
        assert result.main_category == MAIN_AUTO_EXPENSE
        assert result.subcategory == AUTO_GAS
        assert result.status == STATUS_CATEGORIZED
        assert result.confidence >= 0.9

    costco = categorize("COSTCO WHSE #998", normalized_name="Costco")
    amazon = categorize("AMZN MKTPL*AB12C3 AMZN.COM/BILL WA", normalized_name="Amazon")

    for result in [costco, amazon]:
        assert result.main_category == MAIN_PROFIT_LOSS_BUSINESS
        assert result.subcategory in {BUSINESS_OFFICE_EXPENSE, "BUSINESS_OTHER_SUPPLIES"}
        assert result.status == STATUS_NEEDS_REVIEW
        assert result.confidence < 0.7


def test_non_expense_transactions_are_not_applicable() -> None:
    examples = [
        categorize("CAPITAL ONE MOBILE PMT", "CREDIT_CARD_PAYMENT"),
        categorize("MACYS AUTO PYMT", "CREDIT_CARD_PAYMENT"),
        categorize("ATM WITHDRAWAL 08/24 MAIN ST", "ATM_CASH_WITHDRAWAL"),
        categorize("INTEMPUS REALTY PAYROLL", "INCOME", "INFLOW"),
        categorize("ZELLE PAYMENT TO JOHN DOE", "TRANSFER"),
    ]
    for result in examples:
        assert result.main_category is None
        assert result.subcategory is None
        assert result.status == STATUS_NOT_APPLICABLE


def test_interest_bank_fee_medical_office_meals_and_travel_rules() -> None:
    interest_out = categorize("INTEREST CHARGE", "INTEREST", "OUTFLOW")
    interest_in = categorize("INTEREST EARNED", "INTEREST", "INFLOW")
    bank_fee = categorize("MONTHLY SERVICE FEE", "BANK_FEE", "OUTFLOW")
    kaiser = categorize("KAISERDUES PREMIUM", "EXPENSE", "OUTFLOW", "Kaiserdues")
    office = categorize("OFFICE DEPOT 123", "EXPENSE", "OUTFLOW", "Office Depot")
    meal = categorize("STARBUCKS STORE 123", "EXPENSE", "OUTFLOW", "Starbucks")
    hotel = categorize("HOTEL BOOKING", "EXPENSE", "OUTFLOW", "Hotel")

    assert interest_out.main_category == MAIN_PROFIT_LOSS_BUSINESS
    assert interest_out.subcategory == BUSINESS_INTEREST_OTHER
    assert interest_in.status == STATUS_NOT_APPLICABLE

    assert bank_fee.main_category == MAIN_PROFIT_LOSS_BUSINESS
    assert bank_fee.subcategory == BUSINESS_BANK_MEMBERSHIP
    assert bank_fee.status == STATUS_NEEDS_REVIEW

    assert kaiser.main_category == MAIN_PROFIT_LOSS_BUSINESS
    assert kaiser.subcategory == BUSINESS_MEDICAL
    assert office.subcategory == BUSINESS_OFFICE_EXPENSE
    assert meal.subcategory == BUSINESS_TOTAL_MEALS
    assert meal.status == STATUS_NEEDS_REVIEW
    assert hotel.subcategory == BUSINESS_TRAVEL
    assert hotel.status == STATUS_NEEDS_REVIEW


def test_telecom_requires_specific_context() -> None:
    comcast = categorize("COMCAST BUSINESS INTERNET", "EXPENSE", "OUTFLOW", "Comcast")
    verizon_generic = categorize("VERIZON WIRELESS", "EXPENSE", "OUTFLOW", "Verizon")

    assert comcast.main_category == MAIN_BUSINESS_USE_HOME
    assert comcast.subcategory == HOME_TELECOM_INTERNET
    assert verizon_generic.main_category == MAIN_PROFIT_LOSS_BUSINESS
    assert verizon_generic.subcategory == "BUSINESS_OTHER_SUPPLIES"
