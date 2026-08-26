from app.services.statement_terminology.engine import TermDefinition, interpret_description
from app.services.transaction_categorization.base import CategoryClassificationInput
from app.services.transaction_categorization.engine import categorize_transaction
from app.services.transaction_normalization.engine import normalize_transaction_detail
from app.services.transaction_type_detection.base import TypeClassificationInput
from app.services.transaction_type_detection.engine import classify_transaction_type


DEFINITIONS = [
    TermDefinition(1, "PRK", "Parking", "GLOBAL", "GARAGE|METER|CITY", 0.80),
    TermDefinition(2, "PRK", "Parking", "CHASE", "GARAGE|METER|CITY", 0.87),
    TermDefinition(3, "PMT", "Payment", "GLOBAL", "ANY", 0.86),
    TermDefinition(4, "PYMT", "Payment", "GLOBAL", "ANY", 0.86),
    TermDefinition(5, "AUTO PMT", "Automatic Payment", "GLOBAL", "ANY", 0.96),
    TermDefinition(6, "ACH PMT", "ACH Payment", "GLOBAL", "ANY", 0.97),
    TermDefinition(7, "ACH", "Automated Clearing House", "GLOBAL", "ANY", 0.90),
    TermDefinition(8, "AMEX", "American Express", "GLOBAL", "ANY", 0.97),
    TermDefinition(9, "AMZN", "Amazon", "GLOBAL", "ANY", 0.97),
    TermDefinition(10, "MKTPL", "Marketplace", "GLOBAL", "ANY", 0.96),
    TermDefinition(11, "WHSE", "Warehouse", "GLOBAL", "ANY", 0.94),
]


def interpret(detail: str, institution: str = "CHASE"):
    return interpret_description(detail, institution, DEFINITIONS)


def category(detail: str, interpreted_detail: str):
    return categorize_transaction(
        CategoryClassificationInput(
            transaction_detail=detail,
            normalized_name=None,
            transaction_type="EXPENSE",
            direction="OUTFLOW",
            statement_institution="CHASE",
            account_type="CHECKING",
            interpreted_detail=interpreted_detail,
        )
    )


def transaction_type(detail: str, interpreted_detail: str):
    return classify_transaction_type(
        TypeClassificationInput(
            transaction_detail=detail,
            normalized_name=None,
            direction="OUTFLOW",
            statement_institution="CHASE",
            account_type="CHECKING",
            interpreted_detail=interpreted_detail,
        )
    )


def test_token_and_phrase_boundaries_interpret_parking_without_false_substrings() -> None:
    for detail in ["PRK", "CITY PRK", "CITY PRK GARAGE", "SF PRK GARAGE 00928"]:
        result = interpret(detail)
        assert any(match.term == "PRK" and match.meaning == "Parking" for match in result.matches)
        assert "Parking" in result.interpreted_detail

    unrelated = interpret("SPRKLE MARKET")
    assert unrelated.matches == ()
    assert "Parking" not in unrelated.interpreted_detail


def test_institution_specific_term_outranks_global_and_context_boosts_confidence() -> None:
    chase = interpret("CITY PRK GARAGE", "CHASE")
    global_bank = interpret("CITY PRK GARAGE", "CAPITAL_ONE")
    assert chase.matches[0].institution == "CHASE"
    assert chase.matches[0].confidence > global_bank.matches[0].confidence


def test_payment_phrases_are_semantic_signals_not_automobile_categories() -> None:
    for detail in ["PMT", "PYMT"]:
        result = interpret(detail)
        assert result.matches[0].meaning == "Payment"

    automatic = interpret("AUTO PMT")
    assert automatic.interpreted_detail == "Automatic Payment"
    automatic_type = transaction_type("AUTO PMT", automatic.interpreted_detail)
    automatic_category = categorize_transaction(
        CategoryClassificationInput(
            transaction_detail="AUTO PMT",
            normalized_name=None,
            transaction_type=automatic_type.transaction_type,
            direction="OUTFLOW",
            statement_institution="CHASE",
            account_type="CHECKING",
            interpreted_detail=automatic.interpreted_detail,
        )
    )
    assert automatic_category.subcategory != "AUTO_CAR_PAYMENT"

    ach = interpret("ACH PMT")
    assert ach.interpreted_detail == "ACH Payment"
    amex = interpret("AMEX ACH PMT")
    assert transaction_type("AMEX ACH PMT", amex.interpreted_detail).transaction_type == "CREDIT_CARD_PAYMENT"


def test_terminology_drives_normalization_and_valid_low_confidence_categories() -> None:
    amazon = interpret("AMZN MKTPL")
    assert amazon.interpreted_detail == "Amazon Marketplace"
    normalized = normalize_transaction_detail("AMZN MKTPL", interpreted_detail=amazon.interpreted_detail)
    assert normalized.normalized_name == "Amazon Marketplace"
    amazon_category = category("AMZN MKTPL", amazon.interpreted_detail)
    assert amazon_category.main_category == "PROFIT_LOSS_BUSINESS"
    assert amazon_category.subcategory is not None
    assert amazon_category.status == "NEEDS_REVIEW"

    warehouse = interpret("COSTCO WHSE")
    assert warehouse.interpreted_detail == "COSTCO Warehouse"
    warehouse_category = category("COSTCO WHSE", warehouse.interpreted_detail)
    assert warehouse_category.subcategory != "AUTO_GAS"
    assert warehouse_category.status == "NEEDS_REVIEW"


def test_category_examples_use_allowed_categories() -> None:
    examples = {
        "SF PRK GARAGE": ("AUTO_EXPENSE", "AUTO_PARKING"),
        "COSTCO GAS": ("AUTO_EXPENSE", "AUTO_GAS"),
        "CHEVRON": ("AUTO_EXPENSE", "AUTO_GAS"),
        "FASTRAK TOLL": ("AUTO_EXPENSE", "AUTO_TOLLS"),
        "COMCAST": ("BUSINESS_USE_OF_HOME", "HOME_TELECOM_INTERNET"),
        "PG&E": ("BUSINESS_USE_OF_HOME", "HOME_UTILITIES"),
        "RESTAURANT": ("PROFIT_LOSS_BUSINESS", "BUSINESS_TOTAL_MEALS"),
        "UBER": ("PROFIT_LOSS_BUSINESS", "BUSINESS_TRANSPORTATION"),
        "LYFT": ("PROFIT_LOSS_BUSINESS", "BUSINESS_TRANSPORTATION"),
        "HOTEL": ("PROFIT_LOSS_BUSINESS", "BUSINESS_TRAVEL"),
        "AIRLINE": ("PROFIT_LOSS_BUSINESS", "BUSINESS_TRAVEL"),
    }
    for detail, expected in examples.items():
        interpreted = interpret(detail).interpreted_detail
        result = category(detail, interpreted)
        assert (result.main_category, result.subcategory) == expected


def test_confirmed_history_increases_confidence_only_for_exact_term_matches() -> None:
    base = TermDefinition(1, "PRK", "Parking", "GLOBAL", "GARAGE", 0.70, times_confirmed=0)
    learned = TermDefinition(1, "PRK", "Parking", "GLOBAL", "GARAGE", 0.70, times_confirmed=5)
    before = interpret_description("CITY PRK GARAGE", "CHASE", [base])
    after = interpret_description("CITY PRK GARAGE", "CHASE", [learned])
    unrelated = interpret_description("SPRKLE MARKET", "CHASE", [learned])
    assert after.confidence > before.confidence
    assert unrelated.matches == ()


def test_statement_term_api_seeds_and_confirms_meanings(client) -> None:
    listed = client.get("/api/statement-terms")
    assert listed.status_code == 200, listed.text
    prk = next(term for term in listed.json() if term["term"] == "PRK" and term["institution"] == "CHASE")
    confirmed = client.post(f"/api/statement-terms/{prk['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["times_confirmed"] == prk["times_confirmed"] + 1
    assert confirmed.json()["source"] == "USER_CONFIRMED"
