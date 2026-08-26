from __future__ import annotations

from fastapi.testclient import TestClient

from test_transaction_normalization_api import PHASE5_CHASE_TEXT, by_detail, make_pdf


EXPECTED_ANALYSIS_STEPS = [
    "statement_detection",
    "transaction_extraction",
    "transaction_normalization",
    "transaction_type_classification",
    "transaction_categorization",
    "review_notification_refresh",
    "source_file_retention",
]


def _upload_pdf(client: TestClient, filename: str, text: str) -> dict:
    response = client.post(
        "/api/files",
        files=[("files", (filename, make_pdf(text), "application/pdf"))],
    )
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]["file"]


def test_unified_analyze_runs_ordered_pipeline_and_refreshes_attention(client: TestClient) -> None:
    stored_file = _upload_pdf(client, "analysis-chase.pdf", PHASE5_CHASE_TEXT)

    response = client.post(f"/api/files/{stored_file['id']}/analyze")
    attention = client.get("/api/attention")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["failed_step"] is None
    assert [step["key"] for step in payload["steps"]] == EXPECTED_ANALYSIS_STEPS
    assert all(step["status"] == "COMPLETED" for step in payload["steps"])
    assert payload["statement"]["institution"] == "CHASE"
    assert payload["extraction"]["status"] == "EXTRACTED"
    assert len(payload["transactions"]) == 11

    chevron = by_detail(payload["transactions"], "CHEVRON 0094821 FREMONT CA")
    assert chevron["normalized_name"] == "Chevron"
    assert chevron["transaction_type"] == "EXPENSE"
    assert chevron["main_category"] == "AUTO_EXPENSE"
    assert chevron["subcategory"] == "AUTO_GAS"

    assert attention.status_code == 200, attention.text
    assert "TRANSACTION_TYPE_UNKNOWN" in {
        item["attention_type"] for item in attention.json()["items"]
    }


def test_unified_reanalysis_preserves_manual_edits_and_selection(client: TestClient) -> None:
    stored_file = _upload_pdf(client, "analysis-retry-chase.pdf", PHASE5_CHASE_TEXT)
    first = client.post(f"/api/files/{stored_file['id']}/analyze")
    assert first.status_code == 200, first.text
    transactions = first.json()["transactions"]
    amazon = by_detail(transactions, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")
    zelle = by_detail(transactions, "ZELLE PAYMENT TO LAWRENCE VIZCONDE")
    chevron = by_detail(transactions, "CHEVRON 0094821 FREMONT CA")

    name_edit = client.patch(
        f"/api/transactions/{amazon['id']}/normalization",
        json={"normalized_name": "Amazon Business"},
    )
    type_edit = client.patch(f"/api/transactions/{zelle['id']}/type", json={"transaction_type": "EXPENSE"})
    category_edit = client.patch(
        f"/api/transactions/{zelle['id']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_OFFICE_EXPENSE"},
    )
    selection_edit = client.patch(
        f"/api/transactions/{chevron['id']}/inclusion",
        json={"include_in_expenses": False},
    )

    assert name_edit.status_code == 200, name_edit.text
    assert type_edit.status_code == 200, type_edit.text
    assert category_edit.status_code == 200, category_edit.text
    assert selection_edit.status_code == 200, selection_edit.text

    second = client.post(f"/api/files/{stored_file['id']}/analyze")

    assert second.status_code == 200, second.text
    payload = second.json()
    assert payload["status"] == "COMPLETED"
    rows = payload["transactions"]
    amazon_after = by_detail(rows, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")
    zelle_after = by_detail(rows, "ZELLE PAYMENT TO LAWRENCE VIZCONDE")
    chevron_after = by_detail(rows, "CHEVRON 0094821 FREMONT CA")

    assert amazon_after["id"] == amazon["id"]
    assert amazon_after["normalized_name"] == "Amazon Business"
    assert amazon_after["original_normalized_name"] == "Amazon"
    assert amazon_after["user_edited_normalization"] is True
    assert zelle_after["id"] == zelle["id"]
    assert zelle_after["transaction_type"] == "EXPENSE"
    assert zelle_after["original_transaction_type"] == "TRANSFER"
    assert zelle_after["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert zelle_after["subcategory"] == "BUSINESS_OFFICE_EXPENSE"
    assert zelle_after["user_edited_type"] is True
    assert zelle_after["user_edited_category"] is True
    assert chevron_after["id"] == chevron["id"]
    assert chevron_after["include_in_expenses"] is False
    assert chevron_after["inclusion_source"] == "USER_EXCLUDED"


def test_unified_analysis_stops_after_extraction_failure(client: TestClient) -> None:
    stored_file = _upload_pdf(
        client,
        "unsupported-bank.pdf",
        """
        Monthly Financial Statement
        Statement Period 08/01/2026 - 08/31/2026
        Account ending in 4321
        Transaction Detail
        08/20 VENDOR PAYMENT 64.29
        """,
    )

    response = client.post(f"/api/files/{stored_file['id']}/analyze")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "FAILED"
    assert payload["failed_step"] == "transaction_extraction"
    statuses = {step["key"]: step["status"] for step in payload["steps"]}
    assert statuses["statement_detection"] == "COMPLETED"
    assert statuses["transaction_extraction"] == "FAILED"
    assert statuses["transaction_normalization"] == "SKIPPED"
    assert statuses["transaction_type_classification"] == "SKIPPED"
    assert statuses["transaction_categorization"] == "SKIPPED"
    assert statuses["review_notification_refresh"] == "SKIPPED"
    assert statuses["source_file_retention"] == "SKIPPED"
    assert payload["retention"]["removed_count"] == 0
