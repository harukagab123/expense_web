from decimal import Decimal

from fastapi.testclient import TestClient


PHASE5_CHASE_TEXT = """
JPMorgan Chase Bank
Chase Total Checking Statement
Statement Period 08/11/2026 - 09/08/2026
Account ending in 4205
Beginning Balance
Ending Balance
Transaction Detail
ATM & Debit Card Withdrawals
Date Description Amount
08/11 CHEVRON 0094821 FREMONT CA 64.29
08/12 AMZN MKTPL*AB12C3 AMZN.COM/BILL WA 147.29
08/13 COSTCO GAS #01234 55.00
08/14 COSTCO WHSE #998 100.00
08/15 PAYPAL *ADOBE 20.00
08/16 SQ *JOES COFFEE 8.50
08/17 CAPITAL ONE MOBILE PMT 200.00
08/18 AMERICAN EXPRESS ACH PMT 300.00
08/19 ZELLE PAYMENT TO LAWRENCE VIZCONDE 25.00
08/20 CHECK #1024 80.00
08/21 PAYMENT 83726 10.00
Daily Ending Balance
08/21 Ending Balance 1,000.00
"""


def make_pdf(text: str) -> bytes:
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 12 Tf 40 110 Td ({safe}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 260 180] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    body = b"%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return body


def upload_detect_extract(client: TestClient, text: str = PHASE5_CHASE_TEXT) -> tuple[dict, list[dict]]:
    upload = client.post(
        "/api/files",
        files=[("files", ("phase5-chase.pdf", make_pdf(text), "application/pdf"))],
    )
    assert upload.status_code == 200, upload.text
    stored_file = upload.json()["uploaded"][0]["file"]
    statement = client.post(f"/api/files/{stored_file['id']}/detect-statement")
    assert statement.status_code == 200, statement.text
    extracted = client.post(f"/api/statements/{statement.json()['id']}/extract-transactions")
    assert extracted.status_code == 200, extracted.text
    return statement.json(), extracted.json()["transactions"]


def by_detail(transactions: list[dict], detail: str) -> dict:
    return next(transaction for transaction in transactions if transaction["transaction_detail"] == detail)


def test_normalize_statement_transactions_stores_names_separately(client: TestClient) -> None:
    statement, extracted = upload_detect_extract(client)
    raw_before = by_detail(extracted, "CHEVRON 0094821 FREMONT CA")["transaction_detail"]

    response = client.post(f"/api/statements/{statement['id']}/normalize-transactions")

    assert response.status_code == 200, response.text
    transactions = response.json()["transactions"]
    expected = {
        "CHEVRON 0094821 FREMONT CA": "Chevron",
        "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA": "Amazon",
        "COSTCO GAS #01234": "Costco Gas",
        "COSTCO WHSE #998": "Costco",
        "PAYPAL *ADOBE": "Adobe",
        "SQ *JOES COFFEE": "Joe's Coffee",
        "CAPITAL ONE MOBILE PMT": "Capital One",
        "AMERICAN EXPRESS ACH PMT": "American Express",
        "ZELLE PAYMENT TO LAWRENCE VIZCONDE": "Lawrence Vizconde",
        "CHECK #1024": "Check #1024",
    }
    for raw_detail, normalized_name in expected.items():
        transaction = by_detail(transactions, raw_detail)
        assert transaction["transaction_detail"] == raw_detail
        assert transaction["normalized_name"] == normalized_name
        assert transaction["normalization_status"] == "NORMALIZED"
        assert transaction["normalization_confidence"] >= 0.85
        assert transaction["original_normalized_name"] == normalized_name

    unresolved = by_detail(transactions, "PAYMENT 83726")
    assert unresolved["normalized_name"] is None
    assert unresolved["normalization_status"] == "NEEDS_REVIEW"
    assert raw_before == "CHEVRON 0094821 FREMONT CA"


def test_edit_normalized_name_preserves_system_suggestion_and_survives_renormalization(client: TestClient) -> None:
    statement, _ = upload_detect_extract(client)
    normalized = client.post(f"/api/statements/{statement['id']}/normalize-transactions").json()["transactions"]
    amazon = by_detail(normalized, "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")

    edit = client.patch(
        f"/api/transactions/{amazon['id']}/normalization",
        json={"normalized_name": "Amazon Business"},
    )
    renormalized = client.post(f"/api/statements/{statement['id']}/normalize-transactions")

    assert edit.status_code == 200, edit.text
    payload = edit.json()
    assert payload["normalized_name"] == "Amazon Business"
    assert payload["original_normalized_name"] == "Amazon"
    assert payload["normalization_source"] == "USER_EDITED"
    assert payload["normalization_status"] == "USER_CONFIRMED"
    assert payload["user_edited_normalization"] is True

    assert renormalized.status_code == 200
    saved = by_detail(renormalized.json()["transactions"], "AMZN MKTPL*AB12C3 AMZN.COM/BILL WA")
    assert saved["normalized_name"] == "Amazon Business"
    assert saved["original_normalized_name"] == "Amazon"


def test_edit_normalized_name_preserves_manual_category_authority(client: TestClient) -> None:
    statement, _ = upload_detect_extract(client)
    client.post(f"/api/statements/{statement['id']}/normalize-transactions")
    client.post(f"/api/statements/{statement['id']}/classify-transaction-types")
    categorized = client.post(f"/api/statements/{statement['id']}/categorize-transactions")
    chevron = by_detail(categorized.json()["transactions"], "CHEVRON 0094821 FREMONT CA")

    category_edit = client.patch(
        f"/api/transactions/{chevron['id']}/category",
        json={"main_category": "PROFIT_LOSS_BUSINESS", "subcategory": "BUSINESS_OFFICE_EXPENSE"},
    )
    name_edit = client.patch(
        f"/api/transactions/{chevron['id']}/normalization",
        json={"normalized_name": "Chevron Business Fuel"},
    )

    assert category_edit.status_code == 200, category_edit.text
    assert name_edit.status_code == 200, name_edit.text
    saved = name_edit.json()
    assert saved["normalized_name"] == "Chevron Business Fuel"
    assert saved["transaction_type"] == "EXPENSE"
    assert saved["user_edited_type"] is False
    assert saved["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert saved["subcategory"] == "BUSINESS_OFFICE_EXPENSE"
    assert saved["category_status"] == "USER_CONFIRMED"
    assert saved["user_edited_category"] is True


def test_user_future_rule_is_saved_and_outprioritizes_default_rule(client: TestClient) -> None:
    statement, _ = upload_detect_extract(client)
    first = client.post(
        f"/api/statements/{statement['id']}/transactions",
        json={
            "transaction_date": "2026-08-27",
            "transaction_detail": "COMCAST CABLE COMM 12345",
            "amount": "80.00",
            "direction": "OUTFLOW",
        },
    )
    second = client.post(
        f"/api/statements/{statement['id']}/transactions",
        json={
            "transaction_date": "2026-08-28",
            "transaction_detail": "COMCAST CABLE COMM 98765",
            "amount": "82.00",
            "direction": "OUTFLOW",
        },
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    edit = client.patch(
        f"/api/transactions/{first.json()['id']}/normalization",
        json={"normalized_name": "Comcast Home", "use_for_future": True},
    )
    normalized = client.post(f"/api/statements/{statement['id']}/normalize-transactions")

    assert edit.status_code == 200, edit.text
    assert edit.json()["normalization_rule_id"] is not None
    future_match = by_detail(normalized.json()["transactions"], "COMCAST CABLE COMM 98765")
    assert future_match["normalized_name"] == "Comcast Home"
    assert future_match["normalization_source"] == "LEARNED_RULE"


def test_excluded_rows_are_not_normalized_and_manual_rows_are_normalized(client: TestClient) -> None:
    statement, extracted = upload_detect_extract(client)
    payment = by_detail(extracted, "PAYMENT 83726")
    exclude = client.delete(f"/api/transactions/{payment['id']}")
    manual = client.post(
        f"/api/statements/{statement['id']}/transactions",
        json={
            "transaction_date": "2026-08-27",
            "transaction_detail": "Costco Gas #182",
            "amount": "44.25",
            "direction": "OUTFLOW",
        },
    )

    assert exclude.status_code == 200
    assert manual.status_code == 201
    response = client.post(f"/api/statements/{statement['id']}/normalize-transactions")
    lookup = client.get(f"/api/statements/{statement['id']}/transactions?include_excluded=true")

    assert response.status_code == 200
    manual_row = by_detail(response.json()["transactions"], "Costco Gas #182")
    assert manual_row["normalized_name"] == "Costco Gas"

    excluded_row = by_detail(lookup.json()["transactions"], "PAYMENT 83726")
    assert excluded_row["excluded"] is True
    assert excluded_row["normalization_status"] == "NOT_NORMALIZED"
    assert excluded_row["normalized_name"] is None


def test_normalization_uses_current_user_corrected_raw_detail(client: TestClient) -> None:
    statement, extracted = upload_detect_extract(
        client,
        """
        JPMorgan Chase Bank
        Chase Total Checking Statement
        Statement Period 08/11/2026 - 09/08/2026
        Transaction Detail
        ATM & Debit Card Withdrawals
        08/20 CHEVR0N 0094821 FREMONT CA 64.29
        """,
    )
    transaction = extracted[0]
    edited = client.patch(
        f"/api/transactions/{transaction['id']}",
        json={"transaction_detail": "CHEVRON 0094821 FREMONT CA"},
    )
    normalized = client.post(f"/api/statements/{statement['id']}/normalize-transactions")

    assert edited.status_code == 200, edited.text
    assert normalized.status_code == 200
    transaction = normalized.json()["transactions"][0]
    assert transaction["transaction_detail"] == "CHEVRON 0094821 FREMONT CA"
    assert transaction["normalized_name"] == "Chevron"
    assert Decimal(str(transaction["amount"])) == Decimal("64.29")
