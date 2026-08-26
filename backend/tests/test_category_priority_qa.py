from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path

from app.services.statement_terminology.engine import TermDefinition, interpret_description
from app.services.transaction_categorization.base import (
    BUSINESS_OFFICE_EXPENSE,
    BUSINESS_OTHER_SUPPLIES,
    CATEGORY_PRIORITY,
    MATCH_PREFIX,
    MAIN_PROFIT_LOSS_BUSINESS,
    SOURCE_LEARNED_RULE,
    STATUS_NOT_APPLICABLE,
    CategoryClassificationInput,
    UserCategoryRule,
)
from app.services.transaction_categorization.engine import categorize_transaction
from app.services.transaction_categorization.rules import trace_known_category_rules
from app.services.transaction_type_detection.base import TypeClassificationInput
from app.services.transaction_type_detection.engine import classify_transaction_type


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "category_priority_qa.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES = FIXTURE["cases"]

TERMINOLOGY_DEFINITIONS = [
    TermDefinition(1, "PRK", "Parking", "CHASE", "GARAGE|METER|CITY", 0.87),
    TermDefinition(2, "PMT", "Payment", "GLOBAL", "ANY", 0.86),
    TermDefinition(3, "PYMT", "Payment", "GLOBAL", "ANY", 0.86),
    TermDefinition(4, "PAYMNT", "Payment", "GLOBAL", "ANY", 0.88),
    TermDefinition(5, "AUTO PMT", "Automatic Payment", "GLOBAL", "ANY", 0.96),
    TermDefinition(6, "AUTOPAY", "Automatic Payment", "GLOBAL", "ANY", 0.96),
    TermDefinition(7, "ACH PMT", "ACH Payment", "GLOBAL", "ANY", 0.97),
    TermDefinition(8, "ACH", "Automated Clearing House", "GLOBAL", "ANY", 0.90),
    TermDefinition(9, "POS", "Point of Sale", "GLOBAL", "ANY", 0.86),
    TermDefinition(10, "DBT", "Debit", "GLOBAL", "ANY", 0.84),
    TermDefinition(11, "CRD", "Card", "GLOBAL", "ANY", 0.84),
    TermDefinition(12, "AMZN", "Amazon", "GLOBAL", "ANY", 0.97),
    TermDefinition(13, "MKTPL", "Marketplace", "GLOBAL", "ANY", 0.96),
    TermDefinition(14, "WHSE", "Warehouse", "GLOBAL", "ANY", 0.94),
    TermDefinition(15, "AMEX", "American Express", "GLOBAL", "ANY", 0.97),
]


def classify(case: dict, *, user_rules: list[UserCategoryRule] | None = None):
    return categorize_transaction(
        CategoryClassificationInput(
            transaction_detail=case["description"],
            normalized_name=case.get("normalized_name"),
            transaction_type=case["transaction_type"],
            direction=case["direction"],
            statement_institution="CHASE",
            account_type="CHECKING",
            interpreted_detail=case.get("interpreted_detail"),
        ),
        user_rules,
    )


def classification_input(case: dict) -> CategoryClassificationInput:
    return CategoryClassificationInput(
        transaction_detail=case["description"],
        normalized_name=case.get("normalized_name"),
        transaction_type=case["transaction_type"],
        direction=case["direction"],
        statement_institution="CHASE",
        account_type="CHECKING",
        interpreted_detail=case.get("interpreted_detail"),
    )


def test_synthetic_fixture_size_balance_and_expected_distribution() -> None:
    eligible = [case for case in CASES if case["expected_status"] != STATUS_NOT_APPLICABLE]
    non_expenses = [case for case in CASES if case["expected_status"] == STATUS_NOT_APPLICABLE]
    expected_distribution = Counter(case["expected_subcategory"] for case in eligible)

    assert len(CASES) >= 100
    assert len(CASES) == 171
    assert len(eligible) == FIXTURE["expected_eligible_count"] == 159
    assert len(non_expenses) == FIXTURE["expected_non_expense_count"] == 12
    assert expected_distribution[BUSINESS_OTHER_SUPPLIES] == FIXTURE["expected_other_supplies_count"] == 18
    assert expected_distribution[BUSINESS_OTHER_SUPPLIES] / len(eligible) <= 0.15
    assert all(count >= 3 for count in expected_distribution.values())


def test_all_synthetic_results_match_explicit_expectations() -> None:
    failures: list[str] = []
    for case in CASES:
        result = classify(case)
        actual = (result.main_category, result.subcategory, result.status)
        expected = (case["expected_main"], case["expected_subcategory"], case["expected_status"])
        if actual != expected:
            failures.append(f"{case['id']}: {case['description']!r}: expected {expected}, got {actual}")

    assert not failures, "\n" + "\n".join(failures)


def test_actual_other_supplies_distribution_is_bounded_and_intentional() -> None:
    eligible_results = [(case, classify(case)) for case in CASES if case["expected_status"] != STATUS_NOT_APPLICABLE]
    actual_fallbacks = [(case, result) for case, result in eligible_results if result.subcategory == BUSINESS_OTHER_SUPPLIES]
    unexpected = [case["id"] for case, _result in actual_fallbacks if case["expected_subcategory"] != BUSINESS_OTHER_SUPPLIES]

    assert len(actual_fallbacks) / len(eligible_results) <= 0.15
    assert unexpected == []


def test_category_specific_pass_rates_have_no_failures() -> None:
    by_category: dict[str, list[bool]] = defaultdict(list)
    for case in CASES:
        if case["expected_subcategory"] is None:
            continue
        result = classify(case)
        by_category[case["expected_subcategory"]].append(
            (result.main_category, result.subcategory) == (case["expected_main"], case["expected_subcategory"])
        )

    assert len(by_category) == 27
    assert {subcategory: sum(results) for subcategory, results in by_category.items()} == {
        subcategory: len(results) for subcategory, results in by_category.items()
    }


def test_terminology_uses_token_boundaries_and_feeds_parking_evidence() -> None:
    parking = interpret_description("CITY PRK GARAGE", "CHASE", TERMINOLOGY_DEFINITIONS)
    unrelated = [
        interpret_description("SPRKLE MARKET", "CHASE", TERMINOLOGY_DEFINITIONS),
        interpret_description("PRKSON GOODS", "CHASE", TERMINOLOGY_DEFINITIONS),
        interpret_description("XPRK VENDOR", "CHASE", TERMINOLOGY_DEFINITIONS),
    ]
    parking_result = categorize_transaction(
        CategoryClassificationInput(
            transaction_detail="CITY PRK GARAGE TRANSIT CENTER",
            normalized_name=None,
            transaction_type="EXPENSE",
            direction="OUTFLOW",
            statement_institution="CHASE",
            account_type="CHECKING",
            interpreted_detail=parking.interpreted_detail,
        )
    )

    assert parking.interpreted_detail == "CITY Parking GARAGE"
    assert parking_result.subcategory == "AUTO_PARKING"
    assert all(result.matches == () for result in unrelated)


def test_statement_abbreviations_are_interpreted_without_creating_auto_payments() -> None:
    expectations = {
        "PMT": "Payment",
        "PYMT": "Payment",
        "PAYMNT": "Payment",
        "AUTOPAY": "Automatic Payment",
        "ACH": "Automated Clearing House",
        "POS": "Point of Sale",
        "DBT": "Debit",
        "CRD": "Card",
        "AMZN MKTPL": "Amazon Marketplace",
        "COSTCO WHSE": "COSTCO Warehouse",
    }
    for detail, expected in expectations.items():
        assert interpret_description(detail, "CHASE", TERMINOLOGY_DEFINITIONS).interpreted_detail == expected

    for detail in ["MACYS AUTO PYMT", "AMEX AUTO PMT", "CAPITAL ONE AUTOPAY"]:
        interpretation = interpret_description(detail, "CHASE", TERMINOLOGY_DEFINITIONS)
        type_result = classify_transaction_type(
            TypeClassificationInput(
                transaction_detail=detail,
                normalized_name=None,
                direction="OUTFLOW",
                statement_institution="CHASE",
                account_type="CHECKING",
                interpreted_detail=interpretation.interpreted_detail,
            )
        )
        category_result = categorize_transaction(
            CategoryClassificationInput(
                transaction_detail=detail,
                normalized_name=None,
                transaction_type=type_result.transaction_type,
                direction="OUTFLOW",
                statement_institution="CHASE",
                account_type="CHECKING",
                interpreted_detail=interpretation.interpreted_detail,
            )
        )
        assert category_result.subcategory != "AUTO_CAR_PAYMENT"


def test_specific_learned_rule_outranks_generic_rule_and_builtin_priority() -> None:
    rules = [
        UserCategoryRule(
            id=1,
            pattern="COSTCO",
            main_category=MAIN_PROFIT_LOSS_BUSINESS,
            subcategory=BUSINESS_OFFICE_EXPENSE,
            match_type=MATCH_PREFIX,
        ),
        UserCategoryRule(
            id=2,
            pattern="COSTCO GAS",
            main_category=MAIN_PROFIT_LOSS_BUSINESS,
            subcategory=BUSINESS_OTHER_SUPPLIES,
            match_type=MATCH_PREFIX,
        ),
    ]
    result = classify(
        {
            "description": "COSTCO GAS #8821",
            "transaction_type": "EXPENSE",
            "direction": "OUTFLOW",
        },
        user_rules=rules,
    )

    assert result.rule_id == 2
    assert result.source == SOURCE_LEARNED_RULE
    assert result.subcategory == BUSINESS_OTHER_SUPPLIES


def test_priority_catalog_contains_exactly_27_unique_pairs_with_fallback_last() -> None:
    assert len(CATEGORY_PRIORITY) == len(set(CATEGORY_PRIORITY)) == 27
    assert CATEGORY_PRIORITY[-1] == (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_OTHER_SUPPLIES)


def test_runtime_trace_stops_at_first_applicable_priority() -> None:
    cases_by_id = {case["id"]: case for case in CASES}
    expected_last_priority = {
        "collision-01": 4,
        "collision-02": 6,
        "collision-03": 18,
        "collision-04": 14,
        "collision-05": 10,
        "collision-06": 21,
        "interest-01": 16,
        "bank-membership-01": 24,
    }

    for case_id, priority in expected_last_priority.items():
        result, trace = trace_known_category_rules(classification_input(cases_by_id[case_id]))
        assert result.subcategory == cases_by_id[case_id]["expected_subcategory"]
        assert [candidate.priority for candidate in trace] == list(range(1, priority + 1))
        assert trace[-1].applicable is True
        assert trace[-1].score >= 0.5
        assert all(candidate.applicable is False for candidate in trace[:-1])


def test_every_expected_fallback_trace_checks_all_specific_categories_first() -> None:
    fallback_cases = [case for case in CASES if case["expected_subcategory"] == BUSINESS_OTHER_SUPPLIES]

    for case in fallback_cases:
        result, trace = trace_known_category_rules(classification_input(case))
        assert result.subcategory == BUSINESS_OTHER_SUPPLIES
        assert len(trace) == 27
        assert [candidate.priority for candidate in trace] == list(range(1, 28))
        assert all(candidate.applicable is False and candidate.score == 0.0 for candidate in trace[:-1])
        assert trace[-1].applicable is True
        assert trace[-1].score == 0.30
        assert trace[-1].reason == "final fallback after all 26 specific categories failed"


def test_generated_specific_cases_always_beat_explicit_other_supplies_evidence() -> None:
    specific_cases = [
        case
        for case in CASES
        if case["expected_subcategory"] not in {None, BUSINESS_OTHER_SUPPLIES}
    ]

    for case in specific_cases:
        mutated = {**case, "description": f"{case['description']} BUSINESS SUPPLIES"}
        result = classify(mutated)
        assert (result.main_category, result.subcategory) == (
            case["expected_main"],
            case["expected_subcategory"],
        ), case["id"]


def test_generated_nonexpense_cases_never_reach_other_supplies() -> None:
    nonexpense_cases = [case for case in CASES if case["expected_status"] == STATUS_NOT_APPLICABLE]

    for case in nonexpense_cases:
        mutated = {**case, "description": f"{case['description']} BUSINESS SUPPLIES"}
        result = classify(mutated)
        assert result.status == STATUS_NOT_APPLICABLE
        assert result.main_category is None
        assert result.subcategory is None
