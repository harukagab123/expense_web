from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.services.transaction_extraction.base import ExtractedTransaction

from test_transaction_normalization_api import PHASE5_CHASE_TEXT, by_detail, make_pdf


def prepare_phase8_statement(client: TestClient, text: str = PHASE5_CHASE_TEXT) -> tuple[dict, list[dict]]:
    filename = f"phase8-{abs(hash(text))}.pdf"
    upload = client.post(
        "/api/files",
        files=[("files", (filename, make_pdf(text), "application/pdf"))],
    )
    assert upload.status_code == 200, upload.text
    stored_file = upload.json()["uploaded"][0]["file"]
    statement_response = client.post(f"/api/files/{stored_file['id']}/detect-statement")
    assert statement_response.status_code == 200, statement_response.text
    statement = statement_response.json()
    extracted = client.post(f"/api/statements/{statement['id']}/extract-transactions")
    normalized = client.post(f"/api/statements/{statement['id']}/normalize-transactions")
    assert extracted.status_code == 200, extracted.text
    assert normalized.status_code == 200, normalized.text
    classified = client.post(f"/api/statements/{statement['id']}/classify-transaction-types")
    categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    assert classified.status_code == 200, classified.text
    assert categorized.status_code == 200, categorized.text
    return statement, categorized.json()["transactions"]


def selected_count(transactions: list[dict]) -> int:
    return sum(transaction["include_in_expenses"] is True for transaction in transactions)


def selected_total(transactions: list[dict]) -> Decimal:
    total = Decimal("0.00")
    for transaction in transactions:
        if transaction["include_in_expenses"] is True and not transaction["excluded"]:
            total += Decimal(str(transaction["amount"]))
    return total.quantize(Decimal("0.01"))


def test_initial_phase8_state_selects_all_active_transactions_once(client: TestClient) -> None:
    statement, transactions = prepare_phase8_statement(client)

    assert len(transactions) == 11
    assert selected_count(transactions) == 11
    assert all(transaction["inclusion_initialized"] is True for transaction in transactions)
    assert all(transaction["inclusion_source"] == "INITIAL_DEFAULT" for transaction in transactions)

    payment = by_detail(transactions, "PAYMENT 83726")
    excluded = client.delete(f"/api/transactions/{payment['id']}")
    lookup = client.get(f"/api/statements/{statement['id']}/transactions?include_excluded=true")

    assert excluded.status_code == 200, excluded.text
    excluded_row = by_detail(lookup.json()["transactions"], "PAYMENT 83726")
    active_rows = [transaction for transaction in lookup.json()["transactions"] if not transaction["excluded"]]
    assert excluded_row["excluded"] is True
    assert excluded_row["include_in_expenses"] is False
    assert excluded_row["inclusion_source"] == "RECORD_EXCLUDED"
    assert selected_count(active_rows) == 10


def test_single_selection_update_persists_and_can_reselect(client: TestClient) -> None:
    statement, transactions = prepare_phase8_statement(client)
    capital_one = by_detail(transactions, "CAPITAL ONE MOBILE PMT")

    unselect = client.patch(
        f"/api/transactions/{capital_one['id']}/inclusion",
        json={"include_in_expenses": False},
    )
    lookup = client.get(f"/api/statements/{statement['id']}/transactions")
    reselect = client.patch(
        f"/api/transactions/{capital_one['id']}/inclusion",
        json={"include_in_expenses": True},
    )
    reloaded = client.get(f"/api/statements/{statement['id']}/transactions")

    assert unselect.status_code == 200, unselect.text
    assert unselect.json()["include_in_expenses"] is False
    assert unselect.json()["inclusion_source"] == "USER_EXCLUDED"
    saved = by_detail(lookup.json()["transactions"], "CAPITAL ONE MOBILE PMT")
    assert saved["include_in_expenses"] is False

    assert reselect.status_code == 200, reselect.text
    assert reselect.json()["include_in_expenses"] is True
    assert reselect.json()["inclusion_source"] == "USER_SELECTED"
    saved_again = by_detail(reloaded.json()["transactions"], "CAPITAL ONE MOBILE PMT")
    assert saved_again["include_in_expenses"] is True


def test_selection_survives_search_filter_sort_equivalent_refetches_and_recalculation(client: TestClient) -> None:
    statement, transactions = prepare_phase8_statement(client)
    amazon = by_detail(transactions, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")

    unselect = client.patch(f"/api/transactions/{amazon['id']}/inclusion", json={"include_in_expenses": False})
    normalize = client.post(f"/api/statements/{statement['id']}/normalize-transactions")
    classify = client.post(f"/api/statements/{statement['id']}/classify-transaction-types")
    categorize = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    lookup = client.get(f"/api/statements/{statement['id']}/transactions")

    assert unselect.status_code == 200, unselect.text
    assert normalize.status_code == 200
    assert classify.status_code == 200
    assert categorize.status_code == 200
    for rows in [normalize.json()["transactions"], classify.json()["transactions"], categorize.json()["transactions"], lookup.json()["transactions"]]:
        assert by_detail(rows, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")["include_in_expenses"] is False


def test_bulk_inclusion_updates_only_requested_transactions(client: TestClient) -> None:
    statement, transactions = prepare_phase8_statement(client)
    visible = [
        by_detail(transactions, "CHEVRON 0094821 FREMONT CA"),
        by_detail(transactions, "COSTCO GAS #01234"),
        by_detail(transactions, "COSTCO WHSE #998"),
        by_detail(transactions, "PAYPAL *ADOBE"),
        by_detail(transactions, "SQ *JOES COFFEE"),
    ]

    deselect_visible = client.patch(
        "/api/transactions/bulk-inclusion",
        json={"transaction_ids": [transaction["id"] for transaction in visible], "include_in_expenses": False},
    )
    after_deselect = client.get(f"/api/statements/{statement['id']}/transactions").json()["transactions"]
    reselect_visible = client.patch(
        "/api/transactions/bulk-inclusion",
        json={"transaction_ids": [transaction["id"] for transaction in visible], "include_in_expenses": True},
    )
    after_reselect = client.get(f"/api/statements/{statement['id']}/transactions").json()["transactions"]

    assert deselect_visible.status_code == 200, deselect_visible.text
    assert selected_count(after_deselect) == 6
    assert all(by_detail(after_deselect, transaction["transaction_detail"])["include_in_expenses"] is False for transaction in visible)
    assert all(by_detail(after_deselect, transaction["transaction_detail"])["inclusion_source"] == "BULK_USER_EXCLUDED" for transaction in visible)

    assert reselect_visible.status_code == 200, reselect_visible.text
    assert selected_count(after_reselect) == 11
    assert all(by_detail(after_reselect, transaction["transaction_detail"])["include_in_expenses"] is True for transaction in visible)


def test_manual_type_category_and_review_updates_do_not_change_selection(client: TestClient) -> None:
    statement, transactions = prepare_phase8_statement(client)
    amazon = by_detail(transactions, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")

    unselect = client.patch(f"/api/transactions/{amazon['id']}/inclusion", json={"include_in_expenses": False})
    review = client.patch(f"/api/transactions/{amazon['id']}/review", json={"review_status": "REVIEWED"})
    category = client.patch(
        f"/api/transactions/{amazon['id']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_OFFICE_EXPENSE"},
    )
    type_edit = client.patch(f"/api/transactions/{amazon['id']}/type", json={"transaction_type": "EXPENSE"})
    lookup = client.get(f"/api/statements/{statement['id']}/transactions")

    assert unselect.status_code == 200, unselect.text
    assert review.status_code == 200, review.text
    assert review.json()["review_status"] == "REVIEWED"
    assert review.json()["include_in_expenses"] is False
    assert category.status_code == 200, category.text
    assert category.json()["include_in_expenses"] is False
    assert category.json()["review_status"] == "NEEDS_REVIEW"
    assert type_edit.status_code == 200, type_edit.text
    assert type_edit.json()["include_in_expenses"] is False
    saved = by_detail(lookup.json()["transactions"], "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")
    assert saved["include_in_expenses"] is False


def test_multiple_statement_selection_isolation_and_decimal_total(client: TestClient) -> None:
    first_statement, first_transactions = prepare_phase8_statement(client)
    second_text = PHASE5_CHASE_TEXT.replace("CHEVRON 0094821 FREMONT CA", "SHELL OIL 4421")
    second_statement, second_transactions = prepare_phase8_statement(client, second_text)
    first_targets = [
        by_detail(first_transactions, "CAPITAL ONE MOBILE PMT"),
        by_detail(first_transactions, "AMERICAN EXPRESS ACH PMT"),
        by_detail(first_transactions, "ZELLE PAYMENT TO LAWRENCE VIZCONDE"),
    ]

    bulk = client.patch(
        "/api/transactions/bulk-inclusion",
        json={"transaction_ids": [transaction["id"] for transaction in first_targets], "include_in_expenses": False},
    )
    first_lookup = client.get(f"/api/statements/{first_statement['id']}/transactions")
    second_lookup = client.get(f"/api/statements/{second_statement['id']}/transactions")

    assert bulk.status_code == 200, bulk.text
    assert selected_count(first_lookup.json()["transactions"]) == 8
    assert selected_count(second_lookup.json()["transactions"]) == len(second_transactions)
    expected_first_total = selected_total(first_transactions) - Decimal("200.00") - Decimal("300.00") - Decimal("25.00")
    assert selected_total(first_lookup.json()["transactions"]) == expected_first_total.quantize(Decimal("0.01"))


def test_reextraction_preserves_selection_review_and_category_correction(client: TestClient) -> None:
    statement, transactions = prepare_phase8_statement(client)
    amazon = by_detail(transactions, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")
    chevron = by_detail(transactions, "CHEVRON 0094821 FREMONT CA")

    unselect = client.patch(f"/api/transactions/{amazon['id']}/inclusion", json={"include_in_expenses": False})
    review = client.patch(f"/api/transactions/{amazon['id']}/review", json={"review_status": "REVIEWED"})
    category = client.patch(
        f"/api/transactions/{chevron['id']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_TRANSPORTATION"},
    )
    reextract = client.post(f"/api/statements/{statement['id']}/extract-transactions")

    assert unselect.status_code == 200, unselect.text
    assert review.status_code == 200, review.text
    assert category.status_code == 200, category.text
    assert reextract.status_code == 200, reextract.text
    rows = reextract.json()["transactions"]
    saved_amazon = by_detail(rows, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")
    saved_chevron = by_detail(rows, "CHEVRON 0094821 FREMONT CA")
    assert saved_amazon["include_in_expenses"] is False
    assert saved_amazon["review_status"] == "REVIEWED"
    assert saved_chevron["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert saved_chevron["subcategory"] == "BUSINESS_TRANSPORTATION"


def test_reextraction_refreshes_phase8_initialized_machine_rows(client: TestClient) -> None:
    statement, transactions = prepare_phase8_statement(client)
    amazon = by_detail(transactions, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")
    unselect = client.patch(f"/api/transactions/{amazon['id']}/inclusion", json={"include_in_expenses": False})
    assert unselect.status_code == 200, unselect.text

    from app.db.session import get_session_factory
    from app.services.transaction_extraction.service import (
        _create_extraction,
        _replace_unprotected_machine_transactions,
    )

    extracted_transactions = []
    for transaction in transactions:
        detail = transaction["transaction_detail"]
        amount = Decimal(str(transaction["amount"]))
        if detail == "CHEVRON 0094821 FREMONT CA":
            detail = "SHELL OIL 4421"
            amount = Decimal("72.50")
        extracted_transactions.append(
            ExtractedTransaction(
                transaction_date=date.fromisoformat(transaction["transaction_date"]),
                transaction_detail=detail,
                amount=amount,
                direction=transaction["direction"],
                source_page=transaction["source_page"],
                source_order=transaction["source_order"],
                extraction_confidence=transaction["extraction_confidence"],
                needs_review=transaction["needs_review"],
            )
        )

    with get_session_factory()() as session:
        extraction = _create_extraction(
            session,
            statement_id=statement["id"],
            parser_name="test-parser",
            parser_version="test-v1",
            status="EXTRACTING",
            message=None,
        )
        _replace_unprotected_machine_transactions(
            session,
            statement["id"],
            extraction.id,
            extracted_transactions,
        )
        session.commit()

    lookup = client.get(f"/api/statements/{statement['id']}/transactions")
    rows = lookup.json()["transactions"]

    assert lookup.status_code == 200, lookup.text
    assert len(rows) == len(transactions)
    assert Decimal(str(by_detail(rows, "SHELL OIL 4421")["amount"])) == Decimal("72.50")
    assert by_detail(rows, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")["include_in_expenses"] is False
    assert not any(transaction["transaction_detail"] == "CHEVRON 0094821 FREMONT CA" for transaction in rows)
