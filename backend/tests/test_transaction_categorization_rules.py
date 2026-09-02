from app.services.transaction_categorization.base import (
    AUTO_GAS,
    AUTO_PARKING,
    AUTO_TOLLS,
    BUSINESS_INTEREST_OTHER,
    BUSINESS_BANK_MEMBERSHIP,
    BUSINESS_MATERIALS,
    BUSINESS_MEDICAL,
    BUSINESS_OFFICE_EXPENSE,
    BUSINESS_OTHER_SUPPLIES,
    BUSINESS_TOTAL_MEALS,
    BUSINESS_TRANSPORTATION,
    BUSINESS_TRAVEL,
    CATEGORY_CATALOG,
    CATEGORY_PRIORITY,
    CATEGORY_PRIORITY_INDEX,
    HOME_REPAIRS_MAINTENANCE,
    HOME_TELECOM_INTERNET,
    MAIN_AUTO_EXPENSE,
    MAIN_BUSINESS_USE_HOME,
    MAIN_PROFIT_LOSS_BUSINESS,
    STATUS_CATEGORIZED,
    STATUS_NEEDS_REVIEW,
    STATUS_NOT_APPLICABLE,
    CategoryClassificationInput,
    UserCategoryRule,
    MATCH_NORMALIZED_NAME,
    SOURCE_LEARNED_RULE,
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
            "Travel",
            "Total Meals",
            "Transportation",
            "Government",
            "Donations",
            "Bank Membership",
            "Medical",
            "Education & Learning",
            "Other Supplies",
        ],
    }
    assert len(CATEGORY_PRIORITY) == 27
    assert CATEGORY_PRIORITY_INDEX[(MAIN_AUTO_EXPENSE, AUTO_GAS)] == 1
    assert CATEGORY_PRIORITY_INDEX[(MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_OTHER_SUPPLIES)] == 27
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
        assert result.subcategory == BUSINESS_OTHER_SUPPLIES
        assert result.status == STATUS_NEEDS_REVIEW
        assert result.confidence < 0.7


def test_strict_priority_specific_categories_beat_later_generic_categories() -> None:
    examples = {
        "CITY PRK GARAGE": (MAIN_AUTO_EXPENSE, AUTO_PARKING),
        "FASTRAK TOLL": (MAIN_AUTO_EXPENSE, AUTO_TOLLS),
        "OFFICE DEPOT": (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_OFFICE_EXPENSE),
        "PRINTER INK AND PRINTER PAPER": (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_OFFICE_EXPENSE),
        "JOB MATERIALS LUMBER": (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_MATERIALS),
        "ACME MATERIALS SUPPLY": (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_MATERIALS),
        "HOME DEPOT PLUMBING PARTS": (MAIN_BUSINESS_USE_HOME, HOME_REPAIRS_MAINTENANCE),
        "COMCAST CABLE COMM": (MAIN_BUSINESS_USE_HOME, HOME_TELECOM_INTERNET),
        "LOCAL RESTAURANT": (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_TOTAL_MEALS),
        "UBER TRIP": (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_TRANSPORTATION),
        "LYFT RIDE": (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_TRANSPORTATION),
        "HOTEL BOOKING": (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_TRAVEL),
        "UNITED AIRLINES": (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_TRAVEL),
    }

    for detail, expected_pair in examples.items():
        result = categorize(detail)
        assert (result.main_category, result.subcategory) == expected_pair


def test_priority_stops_at_first_applicable_category() -> None:
    parking_and_transportation = categorize("CITY PRK GARAGE UBER")
    toll_and_transportation = categorize("FASTRAK TOLL LYFT")
    materials_and_office = categorize("PROJECT MATERIALS OFFICE DEPOT")

    assert parking_and_transportation.subcategory == AUTO_PARKING
    assert toll_and_transportation.subcategory == AUTO_TOLLS
    assert materials_and_office.subcategory == BUSINESS_MATERIALS


def test_low_confidence_specific_match_still_beats_other_supplies() -> None:
    result = categorize("UNKNOWN MERCHANT PRK 0029")

    assert result.subcategory == AUTO_PARKING
    assert result.confidence < 0.7
    assert result.status == STATUS_NEEDS_REVIEW


def test_ambiguous_expense_uses_low_confidence_final_fallback() -> None:
    result = categorize("QZX MERCHANT 0042")

    assert (result.main_category, result.subcategory) == (
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_OTHER_SUPPLIES,
    )
    assert result.confidence < 0.7
    assert result.status == STATUS_NEEDS_REVIEW


def test_explicit_learned_other_supplies_rule_overrides_priority() -> None:
    result = categorize_transaction(
        CategoryClassificationInput(
            transaction_detail="OFFICE DEPOT ORDER 100",
            normalized_name="Office Depot",
            transaction_type="EXPENSE",
            direction="OUTFLOW",
            statement_institution="CHASE",
            account_type="CHECKING",
        ),
        [
            UserCategoryRule(
                id=77,
                pattern="OFFICE DEPOT",
                main_category=MAIN_PROFIT_LOSS_BUSINESS,
                subcategory=BUSINESS_OTHER_SUPPLIES,
                match_type=MATCH_NORMALIZED_NAME,
            )
        ],
    )

    assert result.subcategory == BUSINESS_OTHER_SUPPLIES
    assert result.source == SOURCE_LEARNED_RULE
    assert result.rule_id == 77


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


def test_clear_restaurant_names_do_not_fall_back_to_other_supplies() -> None:
    examples = [
        "TST*THE CRACK SHACK - LA Las Vegas NV",
        "MANDALAY - HAZEL CAFC LAS VEGAS NV",
        "IMA'S KUSINA HAYWARD HAYWARD CA",
    ]

    for detail in examples:
        result = categorize(detail)
        assert result.main_category == MAIN_PROFIT_LOSS_BUSINESS
        assert result.subcategory == BUSINESS_TOTAL_MEALS
        assert result.status == STATUS_NEEDS_REVIEW


def test_telecom_requires_specific_context() -> None:
    comcast = categorize("COMCAST BUSINESS INTERNET", "EXPENSE", "OUTFLOW", "Comcast")
    verizon_generic = categorize("VERIZON WIRELESS", "EXPENSE", "OUTFLOW", "Verizon")

    assert comcast.main_category == MAIN_BUSINESS_USE_HOME
    assert comcast.subcategory == HOME_TELECOM_INTERNET
    assert verizon_generic.main_category == MAIN_PROFIT_LOSS_BUSINESS
    assert verizon_generic.subcategory == "BUSINESS_OTHER_SUPPLIES"
