from decimal import Decimal

from fastapi.testclient import TestClient

from test_transaction_normalization_api import PHASE5_CHASE_TEXT, by_detail, make_pdf


def upload_detect_extract_normalize(client: TestClient, text: str = PHASE5_CHASE_TEXT) -> tuple[dict, list[dict]]:
    upload = client.post(
        "/api/files",
        files=[("files", ("phase6-chase.pdf", make_pdf(text), "application/pdf"))],
    )
    assert upload.status_code == 200, upload.text
    stored_file = upload.json()["uploaded"][0]["file"]
    statement = client.post(f"/api/files/{stored_file['id']}/detect-statement")
    assert statement.status_code == 200, statement.text
    extracted = client.post(f"/api/statements/{statement.json()['id']}/extract-transactions")
    assert extracted.status_code == 200, extracted.text
    normalized = client.post(f"/api/statements/{statement.json()['id']}/normalize-transactions")
    assert normalized.status_code == 200, normalized.text
    return statement.json(), normalized.json()["transactions"]


def test_classify_statement_transactions_stores_type_separately(client: TestClient) -> None:
    statement, normalized = upload_detect_extract_normalize(client)
    raw_before = by_detail(normalized, "CHEVRON 0094821 FREMONT CA")["transaction_detail"]

    response = client.post(f"/api/statements/{statement['id']}/classify-transaction-types")

    assert response.status_code == 200, response.text
    transactions = response.json()["transactions"]
    expected = {
        "CHEVRON 0094821 FREMONT CA": ("EXPENSE", "YES"),
        "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA": ("EXPENSE", "YES"),
        "COSTCO GAS #01234": ("EXPENSE", "YES"),
        "COSTCO WHSE #998": ("EXPENSE", "YES"),
        "PAYPAL *ADOBE": ("EXPENSE", "YES"),
        "SQ *JOES COFFEE": ("EXPENSE", "YES"),
        "CAPITAL ONE MOBILE PMT": ("CREDIT_CARD_PAYMENT", "NO"),
        "AMERICAN EXPRESS ACH PMT": ("CREDIT_CARD_PAYMENT", "NO"),
        "ZELLE PAYMENT TO LAWRENCE VIZCONDE": ("TRANSFER", "NO"),
        "CHECK #1024": ("CHECK", "REVIEW"),
        "PAYMENT 83726": ("UNKNOWN", "REVIEW"),
    }
    for raw_detail, (transaction_type, suggested_include) in expected.items():
        transaction = by_detail(transactions, raw_detail)
        assert transaction["transaction_detail"] == raw_detail
        assert transaction["transaction_type"] == transaction_type
        assert transaction["suggested_include"] == suggested_include
        assert transaction["original_transaction_type"] == transaction_type

    unknown = by_detail(transactions, "PAYMENT 83726")
    assert unknown["type_status"] == "NEEDS_REVIEW"
    assert raw_before == "CHEVRON 0094821 FREMONT CA"


def test_edit_transaction_type_preserves_system_suggestion_and_survives_reclassification(client: TestClient) -> None:
    statement, _ = upload_detect_extract_normalize(client)
    classified = client.post(f"/api/statements/{statement['id']}/classify-transaction-types").json()["transactions"]
    zelle = by_detail(classified, "ZELLE PAYMENT TO LAWRENCE VIZCONDE")

    edit = client.patch(
        f"/api/transactions/{zelle['id']}/type",
        json={"transaction_type": "EXPENSE"},
    )
    reclassified = client.post(f"/api/statements/{statement['id']}/classify-transaction-types")

    assert edit.status_code == 200, edit.text
    payload = edit.json()
    assert payload["transaction_type"] == "EXPENSE"
    assert payload["original_transaction_type"] == "TRANSFER"
    assert payload["type_source"] == "USER_EDITED"
    assert payload["type_status"] == "USER_CONFIRMED"
    assert payload["user_edited_type"] is True

    saved = by_detail(reclassified.json()["transactions"], "ZELLE PAYMENT TO LAWRENCE VIZCONDE")
    assert saved["transaction_type"] == "EXPENSE"
    assert saved["original_transaction_type"] == "TRANSFER"


def test_user_future_type_rule_is_saved_and_outprioritizes_fallback(client: TestClient) -> None:
    statement, _ = upload_detect_extract_normalize(client)
    first = client.post(
        f"/api/statements/{statement['id']}/transactions",
        json={
            "transaction_date": "2026-08-27",
            "transaction_detail": "KAISERDUES PREMIUM 12345",
            "amount": "80.00",
            "direction": "OUTFLOW",
        },
    )
    second = client.post(
        f"/api/statements/{statement['id']}/transactions",
        json={
            "transaction_date": "2026-08-28",
            "transaction_detail": "KAISERDUES PREMIUM 98765",
            "amount": "82.00",
            "direction": "OUTFLOW",
        },
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    edit = client.patch(
        f"/api/transactions/{first.json()['id']}/type",
        json={"transaction_type": "OTHER", "use_for_future": True},
    )
    classified = client.post(f"/api/statements/{statement['id']}/classify-transaction-types")

    assert edit.status_code == 200, edit.text
    assert edit.json()["type_rule_id"] is not None
    future_match = by_detail(classified.json()["transactions"], "KAISERDUES PREMIUM 98765")
    assert future_match["transaction_type"] == "OTHER"
    assert future_match["type_source"] == "LEARNED_RULE"


def test_excluded_rows_are_not_classified_and_manual_rows_are_classified(client: TestClient) -> None:
    statement, normalized = upload_detect_extract_normalize(client)
    payment = by_detail(normalized, "PAYMENT 83726")
    exclude = client.delete(f"/api/transactions/{payment['id']}")
    manual = client.post(
        f"/api/statements/{statement['id']}/transactions",
        json={
            "transaction_date": "2026-08-27",
            "transaction_detail": "ATM Withdrawal 08/24 1601 E 14th St",
            "amount": "44.25",
            "direction": "OUTFLOW",
        },
    )

    assert exclude.status_code == 200
    assert manual.status_code == 201
    response = client.post(f"/api/statements/{statement['id']}/classify-transaction-types")
    lookup = client.get(f"/api/statements/{statement['id']}/transactions?include_excluded=true")

    assert response.status_code == 200
    manual_row = by_detail(response.json()["transactions"], "ATM Withdrawal 08/24 1601 E 14th St")
    assert manual_row["transaction_type"] == "ATM_CASH_WITHDRAWAL"

    excluded_row = by_detail(lookup.json()["transactions"], "PAYMENT 83726")
    assert excluded_row["excluded"] is True
    assert excluded_row["transaction_type"] == "UNKNOWN"
    assert excluded_row["type_status"] == "NOT_CLASSIFIED"


def test_bulk_type_update_skips_user_edited_types_without_overwrite(client: TestClient) -> None:
    statement, _ = upload_detect_extract_normalize(client)
    classified = client.post(f"/api/statements/{statement['id']}/classify-transaction-types").json()["transactions"]
    zelle = by_detail(classified, "ZELLE PAYMENT TO LAWRENCE VIZCONDE")
    unknown = by_detail(classified, "PAYMENT 83726")

    edit = client.patch(f"/api/transactions/{zelle['id']}/type", json={"transaction_type": "EXPENSE"})
    bulk = client.patch(
        "/api/transactions/bulk-type",
        json={"transaction_ids": [zelle["id"], unknown["id"]], "transaction_type": "OTHER"},
    )
    lookup = client.get(f"/api/statements/{statement['id']}/transactions")

    assert edit.status_code == 200, edit.text
    assert bulk.status_code == 200, bulk.text
    assert zelle["id"] in bulk.json()["skipped_transaction_ids"]
    rows = lookup.json()["transactions"]
    assert by_detail(rows, "ZELLE PAYMENT TO LAWRENCE VIZCONDE")["transaction_type"] == "EXPENSE"
    assert by_detail(rows, "PAYMENT 83726")["transaction_type"] == "OTHER"


def test_classification_uses_current_user_corrected_raw_detail_and_direction(client: TestClient) -> None:
    statement, transactions = upload_detect_extract_normalize(
        client,
        """
        JPMorgan Chase Bank
        Chase Total Checking Statement
        Statement Period 08/11/2026 - 09/08/2026
        Transaction Detail
        ATM & Debit Card Withdrawals
        08/20 PAYROLL ACME INC 64.29
        """,
    )
    transaction = transactions[0]
    edited = client.patch(
        f"/api/transactions/{transaction['id']}",
        json={"transaction_detail": "PAYROLL ACME INC", "direction": "INFLOW"},
    )
    classified = client.post(f"/api/statements/{statement['id']}/classify-transaction-types")

    assert edited.status_code == 200, edited.text
    assert classified.status_code == 200
    transaction = classified.json()["transactions"][0]
    assert transaction["transaction_detail"] == "PAYROLL ACME INC"
    assert transaction["transaction_type"] == "INCOME"
    assert Decimal(str(transaction["amount"])) == Decimal("64.29")
