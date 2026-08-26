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
    assert (costco["main_category"], costco["subcategory"]) == ("PERSONAL_INTERNAL", "UNCATEGORIZED")
    assert costco["category_status"] == "NEEDS_REVIEW"
    assert (amazon["main_category"], amazon["subcategory"]) == ("PERSONAL_INTERNAL", "UNCATEGORIZED")
    assert amazon["category_status"] == "NEEDS_REVIEW"

    for transaction in [capital_one, zelle, check]:
        assert transaction["main_category"] is None
        assert transaction["subcategory"] is None
        assert transaction["category_status"] == "NOT_APPLICABLE"


def test_manual_category_edit_preserves_original_and_survives_recategorization(client: TestClient) -> None:
    statement, transactions = prepare_categorized_statement(client)
    amazon = by_detail(transactions, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")

    edit = client.patch(
        f"/api/transactions/{amazon['id']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_OFFICE_EXPENSE"},
    )
    recategorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")

    assert edit.status_code == 200, edit.text
    edited = edit.json()
    assert edited["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert edited["subcategory"] == "BUSINESS_OFFICE_EXPENSE"
    assert edited["category_source"] == "USER_EDITED"
    assert edited["category_status"] == "USER_CONFIRMED"
    assert edited["original_main_category"] == "PERSONAL_INTERNAL"
    assert edited["original_subcategory"] == "UNCATEGORIZED"

    saved = by_detail(recategorized.json()["transactions"], "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")
    assert saved["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert saved["subcategory"] == "BUSINESS_OFFICE_EXPENSE"


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
    assert zelle_after["main_category"] == "PERSONAL_INTERNAL"
    assert zelle_after["subcategory"] == "UNCATEGORIZED"
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
    categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    lookup = client.get(f"/api/statements/{statement['id']}/transactions?include_excluded=true")

    assert exclude.status_code == 200
    assert invalid_pair.status_code == 422
    manual_row = by_detail(categorized.json()["transactions"], "OFFICE DEPOT 4321")
    assert manual_row["subcategory"] == "BUSINESS_OFFICE_EXPENSE"

    excluded_row = by_detail(lookup.json()["transactions"], "CHEVRON 0094821 FREMONT CA")
    assert excluded_row["excluded"] is True
    assert excluded_row["category_status"] == "CATEGORIZED"
