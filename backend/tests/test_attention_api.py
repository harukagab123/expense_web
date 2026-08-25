from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient


def create_folder(client: TestClient, name: str, parent_folder_id: int | None = None) -> dict:
    response = client.post("/api/folders", json={"name": name, "parent_folder_id": parent_folder_id})
    assert response.status_code == 201, response.text
    return response.json()


def upload_pdf(client: TestClient, filename: str, folder_id: int | None = None) -> dict:
    data = {} if folder_id is None else {"folder_id": str(folder_id)}
    response = client.post(
        "/api/files",
        data=data,
        files=[("files", (filename, b"%PDF-1.4\n%%EOF", "application/pdf"))],
    )
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]["file"]


def create_statement(file_id: int):
    from app.db.session import get_session_factory
    from app.models.statement import Statement

    with get_session_factory()() as session:
        statement = Statement(
            file_id=file_id,
            document_type="BANK_STATEMENT",
            institution="CHASE",
            account_type="CHECKING",
            statement_start_date=date(2026, 8, 1),
            statement_end_date=date(2026, 8, 31),
            detection_status="DETECTED",
            detection_confidence=1.0,
        )
        session.add(statement)
        session.commit()
        session.refresh(statement)
        return statement.id


def add_transaction(
    statement_id: int,
    detail: str,
    *,
    amount: str = "10.00",
    category_status: str = "NOT_CATEGORIZED",
    include_in_expenses: bool = True,
    main_category: str | None = None,
    needs_review: bool = False,
    normalized_name: str | None = None,
    review_status: str = "PENDING",
    source_order: int = 1,
    subcategory: str | None = None,
    transaction_type: str = "EXPENSE",
    type_status: str | None = None,
) -> int:
    from app.db.session import get_session_factory
    from app.models.transaction import Transaction

    with get_session_factory()() as session:
        transaction = Transaction(
            statement_id=statement_id,
            transaction_date=date(2026, 9, 2),
            transaction_detail=detail,
            amount=Decimal(amount),
            direction="OUTFLOW",
            source_order=source_order,
            extraction_confidence=0.95,
            needs_review=needs_review,
            normalized_name=normalized_name or detail.title(),
            normalization_confidence=1.0,
            normalization_source="USER_EDITED",
            normalization_status="USER_CONFIRMED",
            transaction_type=transaction_type,
            type_confidence=1.0 if transaction_type != "UNKNOWN" else 0.0,
            type_source="USER_EDITED" if transaction_type != "UNKNOWN" else "UNRESOLVED",
            type_status=type_status or ("NEEDS_REVIEW" if transaction_type == "UNKNOWN" else "USER_CONFIRMED"),
            suggested_include="REVIEW" if transaction_type == "UNKNOWN" else "YES",
            main_category=main_category,
            subcategory=subcategory,
            category_confidence=1.0 if main_category and subcategory else 0.0,
            category_source="USER_EDITED" if main_category and subcategory else "UNRESOLVED",
            category_status=category_status,
            include_in_expenses=include_in_expenses,
            inclusion_initialized=True,
            inclusion_source="INITIAL_DEFAULT" if include_in_expenses else "USER_EXCLUDED",
            review_status=review_status,
            review_source="SYSTEM",
        )
        session.add(transaction)
        session.commit()
        session.refresh(transaction)
        return transaction.id


def test_attention_required_lawrence_workflow_counts_resolve_without_selection_reset(client: TestClient) -> None:
    year = create_folder(client, "2026")
    chase = create_folder(client, "Chase", year["id"])
    file = upload_pdf(client, "August.pdf", chase["id"])
    statement_id = create_statement(file["id"])
    transaction_id = add_transaction(
        statement_id,
        "Lawrence",
        amount="230.00",
        normalized_name="Lawrence",
        transaction_type="UNKNOWN",
    )

    initial = client.get("/api/attention")

    assert initial.status_code == 200, initial.text
    payload = initial.json()
    assert payload["total"] == 2
    assert {item["attention_type"] for item in payload["items"]} == {
        "CATEGORY_MISSING",
        "TRANSACTION_TYPE_UNKNOWN",
    }
    type_item = next(item for item in payload["items"] if item["attention_type"] == "TRANSACTION_TYPE_UNKNOWN")
    category_item = next(item for item in payload["items"] if item["attention_type"] == "CATEGORY_MISSING")
    assert type_item["file_id"] == file["id"]
    assert type_item["statement_id"] == statement_id
    assert type_item["transaction_id"] == transaction_id
    assert type_item["target_field"] == "transaction_type"
    assert category_item["target_field"] == "main_category"
    assert type_item["folder_path"] == [
        {"id": year["id"], "name": "2026"},
        {"id": chase["id"], "name": "Chase"},
    ]

    type_update = client.patch(f"/api/transactions/{transaction_id}/type", json={"transaction_type": "EXPENSE"})
    after_type = client.get("/api/attention")
    category_update = client.patch(
        f"/api/transactions/{transaction_id}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_OFFICE_EXPENSE"},
    )
    final_count = client.get("/api/attention/count")
    reloaded = client.get(f"/api/statements/{statement_id}/transactions")

    assert type_update.status_code == 200, type_update.text
    assert after_type.json()["total"] == 1
    assert after_type.json()["items"][0]["attention_type"] == "CATEGORY_MISSING"
    assert category_update.status_code == 200, category_update.text
    assert final_count.json()["total"] == 0
    assert final_count.json()["ready_for_summary"] is True
    assert reloaded.json()["transactions"][0]["include_in_expenses"] is True


def test_attention_count_combines_type_category_and_subcategory_issues(client: TestClient) -> None:
    file = upload_pdf(client, "count-test.pdf")
    statement_id = create_statement(file["id"])
    for index in range(2):
        add_transaction(
            statement_id,
            f"Unknown Type {index}",
            category_status="NOT_APPLICABLE",
            source_order=index + 1,
            transaction_type="UNKNOWN",
        )
    for index in range(3):
        add_transaction(statement_id, f"Missing Category {index}", source_order=index + 3)
    add_transaction(
        statement_id,
        "Missing Subcategory",
        main_category="AUTO_EXPENSE",
        source_order=6,
    )

    response = client.get("/api/attention/count")

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 6


def test_summary_excluded_transactions_skip_category_noise_but_keep_extraction_alerts(client: TestClient) -> None:
    file = upload_pdf(client, "excluded-policy.pdf")
    statement_id = create_statement(file["id"])
    add_transaction(statement_id, "Included Missing Category", source_order=1)
    add_transaction(
        statement_id,
        "Summary Excluded Missing Category",
        include_in_expenses=False,
        source_order=2,
    )
    add_transaction(
        statement_id,
        "Summary Excluded Extraction Review",
        include_in_expenses=False,
        needs_review=True,
        source_order=3,
    )
    add_transaction(
        statement_id,
        "Summary Excluded Unknown Type",
        include_in_expenses=False,
        source_order=4,
        transaction_type="UNKNOWN",
    )

    response = client.get("/api/attention")

    assert response.status_code == 200, response.text
    attention_types = [item["attention_type"] for item in response.json()["items"]]
    assert attention_types.count("CATEGORY_MISSING") == 1
    assert "TRANSACTION_EXTRACTION_REVIEW" in attention_types
    assert "TRANSACTION_TYPE_UNKNOWN" in attention_types


def test_reviewed_unknown_transaction_type_is_accepted_and_resolved(client: TestClient) -> None:
    file = upload_pdf(client, "reviewed-unknown-type.pdf")
    statement_id = create_statement(file["id"])
    transaction_id = add_transaction(
        statement_id,
        "Unknown Accepted",
        category_status="NOT_APPLICABLE",
        transaction_type="UNKNOWN",
    )

    before = client.get("/api/attention")
    reviewed = client.patch(f"/api/transactions/{transaction_id}/review", json={"review_status": "REVIEWED"})
    after = client.get("/api/attention")

    assert before.status_code == 200
    assert before.json()["items"][0]["attention_type"] == "TRANSACTION_TYPE_UNKNOWN"
    assert reviewed.status_code == 200, reviewed.text
    assert after.json()["total"] == 0


def test_reviewed_uncategorized_transaction_is_accepted_and_resolved(client: TestClient) -> None:
    file = upload_pdf(client, "reviewed-uncategorized.pdf")
    statement_id = create_statement(file["id"])
    transaction_id = add_transaction(
        statement_id,
        "Amazon",
        category_status="NEEDS_REVIEW",
        main_category="PERSONAL_INTERNAL",
        subcategory="UNCATEGORIZED",
    )

    before = client.get("/api/attention")
    reviewed = client.patch(f"/api/transactions/{transaction_id}/review", json={"review_status": "REVIEWED"})
    after = client.get("/api/attention")

    assert before.status_code == 200
    assert before.json()["items"][0]["attention_type"] == "CATEGORY_UNCATEGORIZED"
    assert reviewed.status_code == 200, reviewed.text
    assert after.json()["total"] == 0
