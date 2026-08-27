from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_session_factory
from app.models.file import StoredFile
from app.models.statement import Statement
from app.models.transaction import Transaction
from app.services.transaction_categorization.base import CATEGORY_CATALOG, CATEGORY_PRIORITY

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "phase9_summary_qa.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def populate_summary_fixture() -> dict[str, int]:
    keys: dict[str, int] = {}
    with get_session_factory()() as session:
        statements: dict[tuple[str, str], Statement] = {}
        source_order: dict[int, int] = {}
        for case in FIXTURE["transactions"]:
            source_key = (case["institution"], case["source_file"])
            statement = statements.get(source_key)
            if statement is None:
                available = case.get("source_available", True)
                stored_file = StoredFile(
                    original_filename=case["source_file"],
                    display_name=case["source_file"],
                    stored_filename=f"synthetic-{len(statements) + 1}.pdf",
                    storage_path=f"synthetic-{len(statements) + 1}.pdf",
                    mime_type="application/pdf",
                    file_size=1,
                    source_file_available=available,
                    source_file_removal_reason=None if available else "RETENTION_LIMIT",
                )
                statement = Statement(
                    file=stored_file,
                    document_type="BANK_STATEMENT",
                    institution=case["institution"],
                    account_type="CHECKING",
                    statement_start_date=date(2025, 1, 1),
                    statement_end_date=date(2026, 12, 31),
                    detection_status="DETECTED",
                )
                session.add(statement)
                session.flush()
                statements[source_key] = statement
                source_order[statement.id] = 0

            source_order[statement.id] += 1
            transaction = Transaction(
                statement=statement,
                transaction_date=date.fromisoformat(case["date"]),
                transaction_detail=case["detail"],
                normalized_name=case["name"],
                amount=Decimal(case["amount"]),
                direction=case["direction"],
                source_order=source_order[statement.id],
                transaction_type=case["type"],
                type_status="CLASSIFIED" if case["type"] != "UNKNOWN" else "NEEDS_REVIEW",
                main_category=case["main"],
                subcategory=case["subcategory"],
                category_confidence=0.95 if case["category_status"] == "CATEGORIZED" else 0.50,
                category_status=case["category_status"],
                include_in_expenses=case["include"],
                inclusion_initialized=True,
                inclusion_source="INITIAL_DEFAULT" if case["include"] else "USER_EXCLUDED",
                review_status=case.get("review_status", "PENDING"),
            )
            session.add(transaction)
            session.flush()
            keys[case["key"]] = transaction.id
        session.commit()
    return keys


def subcategory_map(payload: dict) -> dict[str, dict]:
    return {
        subcategory["id"]: subcategory
        for group in payload["groups"]
        for subcategory in group["subcategories"]
    }


def test_summary_reconciles_all_categories_sources_selections_and_statuses(client: TestClient) -> None:
    populate_summary_fixture()
    response = client.get("/api/summary?tax_year=2026")

    assert response.status_code == 200, response.text
    payload = response.json()
    expected = FIXTURE["expected"]
    assert payload["grand_total"] == expected["grand_total"]
    assert {group["id"]: group["total"] for group in payload["groups"]} == expected["group_totals"]
    assert {key: value["total"] for key, value in subcategory_map(payload).items()} == expected["subcategory_totals"]
    assert payload["metrics"] == {
        "included_eligible_count": expected["included_eligible_count"],
        "contributing_transaction_count": expected["contributing_transaction_count"],
        "needs_review_count": expected["needs_review_count"],
        "source_count": expected["source_count"],
        "not_applicable_count": expected["not_applicable_count"],
        "unselected_count": expected["unselected_count"],
        "other_supplies_count": expected["other_supplies_count"],
    }
    assert payload["readiness"] == "REVIEW_REQUIRED"
    assert [group["id"] for group in payload["groups"]] == [category.id for category in CATEGORY_CATALOG]
    assert [
        (group["id"], subcategory["id"])
        for group in payload["groups"]
        for subcategory in group["subcategories"]
    ] == list(CATEGORY_PRIORITY)
    assert payload["groups"][-1]["subcategories"][-1]["id"] == "BUSINESS_OTHER_SUPPLIES"
    assert sum(Decimal(group["total"]) for group in payload["groups"]) == Decimal(payload["grand_total"])
    for group in payload["groups"]:
        assert sum(Decimal(item["total"]) for item in group["subcategories"]) == Decimal(group["total"])
        for item in group["subcategories"]:
            assert sum(Decimal(row["amount"]) for row in item["transactions"]) == Decimal(item["total"])


def test_year_and_inclusive_custom_date_filters_use_transaction_date(client: TestClient) -> None:
    populate_summary_fixture()
    year_2025 = client.get("/api/summary?tax_year=2025")
    custom = client.get("/api/summary?start_date=2026-01-01&end_date=2026-01-03")
    invalid = client.get("/api/summary?start_date=2026-01-03&end_date=2026-01-01")

    assert year_2025.status_code == 200
    assert year_2025.json()["grand_total"] == "200.00"
    assert custom.status_code == 200
    assert custom.json()["grand_total"] == FIXTURE["expected"]["jan_1_to_3_total"]
    assert custom.json()["period"]["mode"] == "CUSTOM"
    assert invalid.status_code == 422


def test_saved_category_amount_selection_and_date_edits_refresh_summary_without_analysis(client: TestClient) -> None:
    keys = populate_summary_fixture()
    original = client.get("/api/summary?tax_year=2026").json()

    category_edit = client.patch(
        f"/api/transactions/{keys['office']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_MATERIALS"},
    )
    after_category = client.get("/api/summary?tax_year=2026").json()
    assert category_edit.status_code == 200, category_edit.text
    assert subcategory_map(after_category)["BUSINESS_OFFICE_EXPENSE"]["total"] == "50.00"
    assert subcategory_map(after_category)["BUSINESS_MATERIALS"]["total"] == "320.00"
    assert after_category["grand_total"] == original["grand_total"]

    amount_edit = client.patch(f"/api/transactions/{keys['materials']}", json={"amount": "165.00"})
    after_amount = client.get("/api/summary?tax_year=2026").json()
    assert amount_edit.status_code == 200, amount_edit.text
    assert after_amount["grand_total"] == "4160.00"

    unselect = client.patch(
        f"/api/transactions/{keys['materials']}/inclusion",
        json={"include_in_expenses": False},
    )
    after_unselect = client.get("/api/summary?tax_year=2026").json()
    assert unselect.status_code == 200, unselect.text
    assert after_unselect["grand_total"] == "3995.00"
    reselect = client.patch(
        f"/api/transactions/{keys['materials']}/inclusion",
        json={"include_in_expenses": True},
    )
    assert reselect.status_code == 200
    assert client.get("/api/summary?tax_year=2026").json()["grand_total"] == "4160.00"

    date_edit = client.patch(
        f"/api/transactions/{keys['prior-year-gas']}",
        json={"transaction_date": "2026-01-01"},
    )
    assert date_edit.status_code == 200, date_edit.text
    assert client.get("/api/summary?tax_year=2026").json()["grand_total"] == "4360.00"
    assert client.get("/api/summary?tax_year=2025").json()["grand_total"] == "0.00"


def test_review_resolution_preserves_amount_and_reduces_warning(client: TestClient) -> None:
    keys = populate_summary_fixture()
    before = client.get("/api/summary?tax_year=2026").json()
    review = client.patch(
        f"/api/transactions/{keys['office-review']}/review",
        json={"review_status": "REVIEWED"},
    )
    after = client.get("/api/summary?tax_year=2026").json()

    assert review.status_code == 200, review.text
    assert after["grand_total"] == before["grand_total"]
    assert after["metrics"]["needs_review_count"] == before["metrics"]["needs_review_count"] - 1


def test_removed_source_transaction_remains_reportable_and_traceable(client: TestClient) -> None:
    populate_summary_fixture()
    gas = subcategory_map(client.get("/api/summary?tax_year=2026").json())["AUTO_GAS"]
    historical = next(row for row in gas["transactions"] if row["normalized_name"] == "Historical Fuel")

    assert historical["source_file_available"] is False
    assert historical["amount"] == "25.00"
    assert gas["total"] == "325.00"


def test_duplicate_statement_content_is_rejected_even_with_a_different_filename(client: TestClient) -> None:
    content = b"synthetic duplicate statement content"
    first = client.post("/api/files", files=[("files", ("first.txt", content, "text/plain"))])
    second = client.post("/api/files", files=[("files", ("renamed.txt", content, "text/plain"))])

    assert first.status_code == 200
    assert first.json()["failed"] == []
    assert second.status_code == 200
    assert second.json()["uploaded"] == []
    assert second.json()["failed"][0]["error"] == "This file has already been uploaded here."


def test_identical_content_remains_allowed_in_different_folders(client: TestClient) -> None:
    first_folder = client.post("/api/folders", json={"name": "First", "parent_folder_id": None}).json()
    second_folder = client.post("/api/folders", json={"name": "Second", "parent_folder_id": None}).json()
    content = b"synthetic cross-folder duplicate statement"

    first = client.post(
        "/api/files",
        data={"folder_id": first_folder["id"]},
        files=[("files", ("first.txt", content, "text/plain"))],
    )
    second = client.post(
        "/api/files",
        data={"folder_id": second_folder["id"]},
        files=[("files", ("renamed.txt", content, "text/plain"))],
    )

    assert first.status_code == 200
    assert first.json()["failed"] == []
    assert second.status_code == 200
    assert second.json()["failed"] == []
    assert len(second.json()["uploaded"]) == 1


def test_summary_reads_and_export_never_reset_transaction_selections(client: TestClient) -> None:
    keys = populate_summary_fixture()
    with get_session_factory()() as session:
        before = {
            key: session.get(Transaction, transaction_id).include_in_expenses
            for key, transaction_id in keys.items()
        }

    assert client.get("/api/summary?tax_year=2026").status_code == 200
    assert client.get("/api/summary?start_date=2026-01-01&end_date=2026-12-31").status_code == 200
    assert client.get("/api/summary/export.xlsx?tax_year=2026").status_code == 200

    with get_session_factory()() as session:
        after = {
            key: session.get(Transaction, transaction_id).include_in_expenses
            for key, transaction_id in keys.items()
        }
    assert after == before


def test_credit_card_payment_does_not_double_count_underlying_purchases(client: TestClient) -> None:
    populate_summary_fixture()
    payload = client.get("/api/summary?tax_year=2026").json()
    contributing_ids = {
        transaction["id"]
        for group in payload["groups"]
        for subcategory in group["subcategories"]
        for transaction in subcategory["transactions"]
    }
    with get_session_factory()() as session:
        payment = session.execute(
            select(Transaction).where(Transaction.transaction_detail == "AMEX PAYMENT SYNTHETIC")
        ).scalar_one()

    assert payment.id not in contributing_ids
    assert payload["grand_total"] == FIXTURE["expected"]["grand_total"]


def test_excel_export_reopens_with_required_sheets_order_and_reconciled_numeric_totals(
    client: TestClient,
) -> None:
    from app.services.expense_summary.export import inspect_expense_summary_workbook

    populate_summary_fixture()
    response = client.get("/api/summary/export.xlsx?tax_year=2026")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    inspection = inspect_expense_summary_workbook(response.content)
    assert inspection["sheets"] == ["Summary", "Transaction Detail"]
    assert not any(
        error in inspection["formulaErrors"]
        for error in ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A")
    )
    detail_rows = inspection["detailValues"]
    assert detail_rows[0][:10] == [
        "Date",
        "Name",
        "Transaction Detail",
        "Institution",
        "Source File",
        "Transaction Type",
        "Main Category",
        "Subcategory",
        "Amount",
        "Review Status",
    ]
    assert len(detail_rows) - 1 == FIXTURE["expected"]["contributing_transaction_count"]
    assert sum(Decimal(str(row[8])) for row in detail_rows[1:]) == Decimal(FIXTURE["expected"]["grand_total"])
    summary_total_row = next(
        row for row in inspection["summaryValues"] if row and row[0] == "TOTAL INCLUDED EXPENSES"
    )
    assert Decimal(str(summary_total_row[2])) == Decimal(FIXTURE["expected"]["grand_total"])
    summary_labels = [row[0] for row in inspection["summaryValues"] if row and row[0]]
    assert summary_labels.index("Education & Learning") < summary_labels.index("Other Supplies")
    assert isinstance(detail_rows[1][8], (int, float))
