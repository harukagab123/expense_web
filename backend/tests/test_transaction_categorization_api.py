from fastapi.testclient import TestClient

from test_transaction_normalization_api import by_detail
from test_transaction_type_detection_api import upload_detect_extract_normalize


def prepare_categorized_statement(client: TestClient) -> tuple[dict, list[dict]]:
    statement, _ = upload_detect_extract_normalize(client)
    classified = client.post(f"/api/statements/{statement['id']}/classify-transaction-types")
    assert classified.status_code == 200, classified.text
    categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    assert categorized.status_code == 200, categorized.text
    return statement, categorized.json()["transactions"]


def add_typed_transaction(
    client: TestClient,
    statement_id: int,
    detail: str,
    transaction_type: str,
    *,
    direction: str = "OUTFLOW",
) -> dict:
    created = client.post(
        f"/api/statements/{statement_id}/transactions",
        json={
            "transaction_date": "2026-08-27",
            "transaction_detail": detail,
            "amount": "44.25",
            "direction": direction,
        },
    )
    assert created.status_code == 201, created.text
    typed = client.patch(f"/api/transactions/{created.json()['id']}/type", json={"transaction_type": transaction_type})
    assert typed.status_code == 200, typed.text
    return typed.json()


def test_category_catalog_endpoint_exposes_requested_hierarchy(client: TestClient) -> None:
    response = client.get("/api/categories/catalog")

    assert response.status_code == 200, response.text
    categories = response.json()["categories"]
    auto = next(category for category in categories if category["id"] == "AUTO_EXPENSE")
    business = next(category for category in categories if category["id"] == "PROFIT_LOSS_BUSINESS")

    assert auto["label"] == "AUTO EXPENSE"
    assert [subcategory["label"] for subcategory in auto["subcategories"]] == [
        "Gas",
        "Insurance",
        "Car Maintenance",
        "Parking Fee",
        "Tires",
        "Tolls",
        "Car Payment",
    ]
    assert "Office Expense" in [subcategory["label"] for subcategory in business["subcategories"]]
    assert [subcategory["label"] for subcategory in business["subcategories"]] == [
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
    ]


def test_categorize_statement_separates_expenses_from_non_expenses(client: TestClient) -> None:
    _statement, transactions = prepare_categorized_statement(client)

    chevron = by_detail(transactions, "CHEVRON 0094821 FREMONT CA")
    amazon = by_detail(transactions, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")
    costco_gas = by_detail(transactions, "COSTCO GAS #01234")
    costco = by_detail(transactions, "COSTCO WHSE #998")
    capital_one = by_detail(transactions, "CAPITAL ONE MOBILE PMT")
    zelle = by_detail(transactions, "ZELLE PAYMENT TO LAWRENCE VIZCONDE")
    check = by_detail(transactions, "CHECK #1024")

    assert (chevron["main_category"], chevron["subcategory"]) == ("AUTO_EXPENSE", "AUTO_GAS")
    assert chevron["category_status"] == "CATEGORIZED"
    assert chevron["category_confidence"] >= 0.9

    assert (costco_gas["main_category"], costco_gas["subcategory"]) == ("AUTO_EXPENSE", "AUTO_GAS")
    assert (costco["main_category"], costco["subcategory"]) == ("PROFIT_LOSS_BUSINESS", "BUSINESS_OTHER_SUPPLIES")
    assert costco["category_status"] == "NEEDS_REVIEW"
    assert (amazon["main_category"], amazon["subcategory"]) == ("PROFIT_LOSS_BUSINESS", "BUSINESS_OTHER_SUPPLIES")
    assert amazon["category_status"] == "NEEDS_REVIEW"
    attention = client.get("/api/attention")
    assert attention.status_code == 200, attention.text
    assert any(
        item["transaction_id"] == amazon["id"]
        and item["attention_type"] == "CATEGORY_NEEDS_REVIEW"
        and item["target_field"] == "main_category"
        for item in attention.json()["items"]
    )

    for transaction in [capital_one, zelle, check]:
        assert transaction["main_category"] is None
        assert transaction["subcategory"] is None
        assert transaction["category_status"] == "NOT_APPLICABLE"

    for transaction in transactions:
        if transaction["transaction_type"] in {"EXPENSE", "BANK_FEE"}:
            assert transaction["main_category"] is not None
            assert transaction["subcategory"] is not None


def test_manual_category_edit_preserves_original_and_survives_recategorization(client: TestClient) -> None:
    statement, transactions = prepare_categorized_statement(client)
    office_depot = add_typed_transaction(client, statement["id"], "OFFICE DEPOT 7721", "EXPENSE")
    categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    assert categorized.status_code == 200, categorized.text
    office_depot = by_detail(categorized.json()["transactions"], "OFFICE DEPOT 7721")
    assert office_depot["subcategory"] == "BUSINESS_OFFICE_EXPENSE"
    selection_edit = client.patch(
        f"/api/transactions/{office_depot['id']}/inclusion",
        json={"include_in_expenses": False},
    )
    assert selection_edit.status_code == 200, selection_edit.text

    edit = client.patch(
        f"/api/transactions/{office_depot['id']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_OTHER_SUPPLIES"},
    )
    recategorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")

    assert edit.status_code == 200, edit.text
    edited = edit.json()
    assert edited["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert edited["subcategory"] == "BUSINESS_OTHER_SUPPLIES"
    assert edited["category_source"] == "USER_EDITED"
    assert edited["category_status"] == "USER_CONFIRMED"
    assert edited["original_main_category"] == "PROFIT_LOSS_BUSINESS"
    assert edited["original_subcategory"] == "BUSINESS_OFFICE_EXPENSE"

    saved = by_detail(recategorized.json()["transactions"], "OFFICE DEPOT 7721")
    assert saved["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert saved["subcategory"] == "BUSINESS_OTHER_SUPPLIES"
    assert saved["include_in_expenses"] is False


def test_saved_category_rule_applies_to_future_similar_transactions(client: TestClient) -> None:
    statement, _transactions = prepare_categorized_statement(client)
    first = add_typed_transaction(client, statement["id"], "ODD VENDOR SOFTWARE 12345", "EXPENSE")
    second = add_typed_transaction(client, statement["id"], "ODD VENDOR SOFTWARE 98765", "EXPENSE")

    edit = client.patch(
        f"/api/transactions/{first['id']}/category",
        json={
            "main_category": "PROFIT_LOSS_BUSINESS",
            "subcategory": "BUSINESS_OFFICE_EXPENSE",
            "use_for_future": True,
        },
    )
    categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")

    assert edit.status_code == 200, edit.text
    assert edit.json()["category_rule_id"] is not None
    future = by_detail(categorized.json()["transactions"], "ODD VENDOR SOFTWARE 98765")
    assert future["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert future["subcategory"] == "BUSINESS_OFFICE_EXPENSE"
    assert future["category_source"] == "LEARNED_RULE"
    unrelated = by_detail(categorized.json()["transactions"], "CHEVRON 0094821 FREMONT CA")
    assert unrelated["subcategory"] == "AUTO_GAS"
    assert second["category_status"] == "NOT_CATEGORIZED"


def test_type_changes_update_category_eligibility(client: TestClient) -> None:
    statement, transactions = prepare_categorized_statement(client)
    zelle = by_detail(transactions, "ZELLE PAYMENT TO LAWRENCE VIZCONDE")
    chevron = by_detail(transactions, "CHEVRON 0094821 FREMONT CA")

    zelle_type_edit = client.patch(f"/api/transactions/{zelle['id']}/type", json={"transaction_type": "EXPENSE"})
    zelle_categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    chevron_type_edit = client.patch(
        f"/api/transactions/{chevron['id']}/type",
        json={"transaction_type": "CREDIT_CARD_PAYMENT"},
    )

    assert zelle_type_edit.status_code == 200, zelle_type_edit.text
    zelle_after = by_detail(zelle_categorized.json()["transactions"], "ZELLE PAYMENT TO LAWRENCE VIZCONDE")
    assert zelle_after["transaction_type"] == "EXPENSE"
    assert zelle_after["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert zelle_after["subcategory"] == "BUSINESS_OTHER_SUPPLIES"
    assert zelle_after["category_status"] == "NEEDS_REVIEW"

    assert chevron_type_edit.status_code == 200, chevron_type_edit.text
    chevron_after = chevron_type_edit.json()
    assert chevron_after["transaction_type"] == "CREDIT_CARD_PAYMENT"
    assert chevron_after["main_category"] is None
    assert chevron_after["subcategory"] is None
    assert chevron_after["category_status"] == "NOT_APPLICABLE"


def test_category_edits_allow_any_active_type_and_bulk_skips_protected_rows(client: TestClient) -> None:
    _statement, transactions = prepare_categorized_statement(client)
    chevron = by_detail(transactions, "CHEVRON 0094821 FREMONT CA")
    amazon = by_detail(transactions, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")
    capital_one = by_detail(transactions, "CAPITAL ONE MOBILE PMT")
    zelle = by_detail(transactions, "ZELLE PAYMENT TO LAWRENCE VIZCONDE")

    edit = client.patch(
        f"/api/transactions/{amazon['id']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_OFFICE_EXPENSE"},
    )
    non_expense_edit = client.patch(
        f"/api/transactions/{capital_one['id']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_BANK_MEMBERSHIP"},
    )
    bulk = client.patch(
        "/api/transactions/bulk-category",
        json={
            "transaction_ids": [chevron["id"], amazon["id"], capital_one["id"], zelle["id"]],
            "main_category": "PROFIT_LOSS_BUSINESS",
            "subcategory": "BUSINESS_MATERIALS",
        },
    )

    assert edit.status_code == 200, edit.text
    assert non_expense_edit.status_code == 200, non_expense_edit.text
    assert bulk.status_code == 200, bulk.text
    skipped = bulk.json()["skipped_transaction_ids"]
    assert amazon["id"] in skipped
    assert capital_one["id"] in skipped
    assert zelle["id"] not in skipped
    rows = bulk.json()["transactions"]
    chevron_after = next(transaction for transaction in rows if transaction["id"] == chevron["id"])
    assert chevron_after["subcategory"] == "BUSINESS_MATERIALS"
    capital_one_after = next(transaction for transaction in rows if transaction["id"] == capital_one["id"])
    assert capital_one_after["subcategory"] == "BUSINESS_BANK_MEMBERSHIP"
    zelle_after = next(transaction for transaction in rows if transaction["id"] == zelle["id"])
    assert zelle_after["subcategory"] == "BUSINESS_MATERIALS"


def test_category_validation_excluded_rows_and_manual_rows(client: TestClient) -> None:
    statement, transactions = prepare_categorized_statement(client)
    chevron = by_detail(transactions, "CHEVRON 0094821 FREMONT CA")
    exclude = client.delete(f"/api/transactions/{chevron['id']}")
    manual = add_typed_transaction(client, statement["id"], "OFFICE DEPOT 4321", "EXPENSE")

    invalid_pair = client.patch(
        f"/api/transactions/{manual['id']}/category",
        json={"main_category": "AUTO_EXPENSE", "subcategory": "BUSINESS_OFFICE_EXPENSE"},
    )
    removed_category = client.patch(
        f"/api/transactions/{manual['id']}/category",
        json={"main_category": "PERSONAL_INTERNAL", "subcategory": "UNCATEGORIZED"},
    )
    removed_subcategory = client.patch(
        f"/api/transactions/{manual['id']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "PERSONAL_OTHER_ITEMS"},
    )
    categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    lookup = client.get(f"/api/statements/{statement['id']}/transactions?include_excluded=true")

    assert exclude.status_code == 200
    assert invalid_pair.status_code == 422
    assert removed_category.status_code == 422
    assert removed_subcategory.status_code == 422
    manual_row = by_detail(categorized.json()["transactions"], "OFFICE DEPOT 4321")
    assert manual_row["subcategory"] == "BUSINESS_OFFICE_EXPENSE"

    excluded_row = by_detail(lookup.json()["transactions"], "CHEVRON 0094821 FREMONT CA")
    assert excluded_row["excluded"] is True
    assert excluded_row["category_status"] == "CATEGORIZED"


def test_recategorization_preserves_user_confirmed_category_for_unknown_outflow_and_summary(
    client: TestClient,
) -> None:
    statement, _transactions = prepare_categorized_statement(client)
    created = client.post(
        f"/api/statements/{statement['id']}/transactions",
        json={
            "transaction_date": "2026-08-31",
            "transaction_detail": "QA UNKNOWN OFFICE PURCHASE",
            "amount": "13.34",
            "direction": "OUTFLOW",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["transaction_type"] == "UNKNOWN"

    edited = client.patch(
        f"/api/transactions/{created.json()['id']}/category",
        json={
            "main_category": "PROFIT_LOSS_BUSINESS",
            "subcategory": "BUSINESS_OFFICE_EXPENSE",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["user_edited_category"] is True

    before = client.get("/api/summary?tax_year=2026")
    assert before.status_code == 200, before.text
    assert created.json()["id"] in {
        row["id"]
        for group in before.json()["groups"]
        for subcategory in group["subcategories"]
        for row in subcategory["transactions"]
    }

    categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    assert categorized.status_code == 200, categorized.text
    preserved = by_detail(categorized.json()["transactions"], "QA UNKNOWN OFFICE PURCHASE")
    assert preserved["transaction_type"] == "UNKNOWN"
    assert preserved["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert preserved["subcategory"] == "BUSINESS_OFFICE_EXPENSE"
    assert preserved["category_status"] == "USER_CONFIRMED"
    assert preserved["user_edited_category"] is True

    after = client.get("/api/summary?tax_year=2026")
    assert after.status_code == 200, after.text
    assert preserved["id"] in {
        row["id"]
        for group in after.json()["groups"]
        for subcategory in group["subcategories"]
        for row in subcategory["transactions"]
    }


def set_normalized_name(client: TestClient, transaction: dict, normalized_name: str) -> dict:
    response = client.patch(
        f"/api/transactions/{transaction['id']}/normalization",
        json={"normalized_name": normalized_name},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_normalized_learned_rule_conflict_management_and_selection_preservation(client: TestClient) -> None:
    statement, _transactions = prepare_categorized_statement(client)
    first = set_normalized_name(
        client,
        add_typed_transaction(client, statement["id"], "COMCAST CABLE COMM", "EXPENSE"),
        "Comcast",
    )
    future = set_normalized_name(
        client,
        add_typed_transaction(client, statement["id"], "COMCAST CABLE COMM PAYMENT", "EXPENSE"),
        "Comcast",
    )
    excluded = client.patch(
        f"/api/transactions/{future['id']}/inclusion",
        json={"include_in_expenses": False},
    )
    assert excluded.status_code == 200, excluded.text

    learned = client.patch(
        f"/api/transactions/{first['id']}/category",
        json={
            "main_category": "BUSINESS_USE_OF_HOME",
            "subcategory": "HOME_TELECOM_INTERNET",
            "use_for_future": True,
        },
    )
    assert learned.status_code == 200, learned.text
    assert learned.json()["category_rule_id"] is not None

    categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    future_after = by_detail(categorized.json()["transactions"], "COMCAST CABLE COMM PAYMENT")
    assert (future_after["main_category"], future_after["subcategory"]) == (
        "BUSINESS_USE_OF_HOME",
        "HOME_TELECOM_INTERNET",
    )
    assert future_after["category_source"] == "LEARNED_RULE"
    assert future_after["include_in_expenses"] is False
    attention = client.get("/api/attention")
    assert attention.status_code == 200, attention.text
    assert not any(
        item["transaction_id"] == future["id"] and item["attention_type"] == "CATEGORY_MISSING"
        for item in attention.json()["items"]
    )

    confirmed_again = client.patch(
        f"/api/transactions/{future['id']}/category",
        json={
            "main_category": "BUSINESS_USE_OF_HOME",
            "subcategory": "HOME_TELECOM_INTERNET",
            "use_for_future": True,
        },
    )
    assert confirmed_again.status_code == 200, confirmed_again.text
    repeated_rules = client.get("/api/category-rules").json()
    assert len(repeated_rules) == 1
    assert repeated_rules[0]["times_confirmed"] == 2

    conflict = client.patch(
        f"/api/transactions/{first['id']}/category",
        json={
            "main_category": "PROFIT_LOSS_BUSINESS",
            "subcategory": "BUSINESS_OFFICE_EXPENSE",
            "use_for_future": True,
        },
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "CATEGORY_RULE_CONFLICT"

    rules_before_replace = client.get("/api/category-rules")
    assert rules_before_replace.status_code == 200, rules_before_replace.text
    comcast_rule = next(rule for rule in rules_before_replace.json() if rule["pattern"] == "COMCAST")
    assert comcast_rule["subcategory"] == "HOME_TELECOM_INTERNET"

    replaced = client.patch(
        f"/api/transactions/{first['id']}/category",
        json={
            "main_category": "PROFIT_LOSS_BUSINESS",
            "subcategory": "BUSINESS_OFFICE_EXPENSE",
            "use_for_future": True,
            "replace_existing_rule": True,
        },
    )
    assert replaced.status_code == 200, replaced.text

    edited_rule = client.patch(
        f"/api/category-rules/{comcast_rule['id']}",
        json={"main_category": "BUSINESS_USE_OF_HOME", "subcategory": "HOME_UTILITIES"},
    )
    assert edited_rule.status_code == 200, edited_rule.text
    assert edited_rule.json()["subcategory"] == "HOME_UTILITIES"

    deleted = client.delete(f"/api/category-rules/{comcast_rule['id']}")
    assert deleted.status_code == 204, deleted.text
    assert client.get("/api/category-rules").json() == []

    historical = client.get(f"/api/statements/{statement['id']}/transactions").json()["transactions"]
    historical_future = by_detail(historical, "COMCAST CABLE COMM PAYMENT")
    assert historical_future["subcategory"] == "HOME_TELECOM_INTERNET"
    assert historical_future["include_in_expenses"] is False


def test_ambiguous_merchants_only_learn_when_explicit_and_specific(client: TestClient) -> None:
    statement, _transactions = prepare_categorized_statement(client)
    generic_amazon = set_normalized_name(
        client,
        add_typed_transaction(client, statement["id"], "AMAZON MARKETPLACE ORDER", "EXPENSE"),
        "Amazon",
    )
    amazon_business = set_normalized_name(
        client,
        add_typed_transaction(client, statement["id"], "AMAZON BUSINESS ORDER 101", "EXPENSE"),
        "Amazon Business",
    )
    future_business = set_normalized_name(
        client,
        add_typed_transaction(client, statement["id"], "AMAZON BUSINESS ORDER 202", "EXPENSE"),
        "Amazon Business",
    )

    one_off = client.patch(
        f"/api/transactions/{generic_amazon['id']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_OFFICE_EXPENSE"},
    )
    assert one_off.status_code == 200, one_off.text
    assert client.get("/api/category-rules").json() == []

    explicit = client.patch(
        f"/api/transactions/{amazon_business['id']}/category",
        json={
            "main_category": "PROFIT_LOSS_BUSINESS",
            "subcategory": "BUSINESS_OFFICE_EXPENSE",
            "use_for_future": True,
        },
    )
    assert explicit.status_code == 200, explicit.text

    categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    rows = categorized.json()["transactions"]
    business_after = by_detail(rows, "AMAZON BUSINESS ORDER 202")
    generic_after = by_detail(rows, "AMAZON MARKETPLACE ORDER")
    assert business_after["category_source"] == "LEARNED_RULE"
    assert business_after["subcategory"] == "BUSINESS_OFFICE_EXPENSE"
    assert generic_after["category_source"] == "USER_EDITED"

    another_generic = set_normalized_name(
        client,
        add_typed_transaction(client, statement["id"], "AMAZON MARKETPLACE ORDER 303", "EXPENSE"),
        "Amazon",
    )
    categorized_again = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    another_generic_after = by_detail(categorized_again.json()["transactions"], "AMAZON MARKETPLACE ORDER 303")
    assert another_generic_after["category_source"] != "LEARNED_RULE"
    assert another_generic_after["id"] == another_generic["id"]
