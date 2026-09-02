from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient


CHASE_TRANSACTION_TEXT = """
JPMorgan Chase Bank
Chase Total Checking Statement
Statement Period 08/11/2026 - 09/08/2026
Account ending in 4205
Beginning Balance
Ending Balance
Transaction Detail
Deposits and Additions
Date Description Amount
08/15 PAYROLL ACME INC 1,250.00
ATM & Debit Card Withdrawals
08/18 AMAZON MKTPL*12345
      AMZN.COM/BILL WA
      147.29
08/20 CHEVRON 0094821 FREMONT CA 64.29
Electronic Withdrawals
08/20 PAYMENT TO CHASE CARD 500.00
Fees
08/25 Monthly Service Fee 12.00
Daily Ending Balance
08/25 Ending Balance 1,526.42
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


def upload_file(client: TestClient, filename: str, text: str) -> dict:
    response = client.post(
        "/api/files",
        files=[("files", (filename, make_pdf(text), "application/pdf"))],
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["failed"] == []
    return payload["uploaded"][0]["file"]


def detect_statement(client: TestClient, file_id: int) -> dict:
    response = client.post(f"/api/files/{file_id}/detect-statement")
    assert response.status_code == 200, response.text
    return response.json()


def amount(value) -> Decimal:
    return Decimal(str(value))


def test_extract_chase_transactions_from_uploaded_pdf(client: TestClient) -> None:
    stored_file = upload_file(client, "chase-transactions.pdf", CHASE_TRANSACTION_TEXT)
    statement = detect_statement(client, stored_file["id"])

    response = client.post(f"/api/statements/{statement['id']}/extract-transactions")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["extraction"]["parser_name"] == "chase"
    assert payload["extraction"]["parser_version"] == "chase-v1"
    assert payload["extraction"]["status"] == "EXTRACTED"
    assert payload["extraction"]["transaction_count"] == 5
    assert payload["extraction"]["review_count"] == 0

    transactions = payload["transactions"]
    assert [transaction["transaction_detail"] for transaction in transactions] == [
        "PAYROLL ACME INC",
        "AMAZON MKTPL*12345 AMZN.COM/BILL WA",
        "CHEVRON 0094821 FREMONT CA",
        "PAYMENT TO CHASE CARD",
        "Monthly Service Fee",
    ]
    assert [transaction["direction"] for transaction in transactions] == [
        "INFLOW",
        "OUTFLOW",
        "OUTFLOW",
        "OUTFLOW",
        "OUTFLOW",
    ]
    assert [amount(transaction["amount"]) for transaction in transactions] == [
        Decimal("1250.00"),
        Decimal("147.29"),
        Decimal("64.29"),
        Decimal("500.00"),
        Decimal("12.00"),
    ]
    assert [transaction["source_order"] for transaction in transactions] == [1, 2, 3, 4, 5]
    assert all(transaction["source_page"] == 1 for transaction in transactions)
    assert all(transaction["original_transaction_detail"] for transaction in transactions)


def test_extraction_uses_current_corrected_statement_institution(client: TestClient) -> None:
    stored_file = upload_file(
        client,
        "capital-one-corrected-to-chase.pdf",
        """
        Capital One Bank
        Credit Card Account Summary
        Statement Period 08/11/2026 to 09/08/2026
        New Balance
        Transaction Detail
        Deposits and Additions
        08/15 PAYROLL ACME INC 1,250.00
        """,
    )
    statement = detect_statement(client, stored_file["id"])
    assert statement["institution"] == "CAPITAL_ONE"

    correction = client.patch(f"/api/files/{stored_file['id']}/statement", json={"institution": "CHASE"})
    assert correction.status_code == 200, correction.text

    response = client.post(f"/api/statements/{statement['id']}/extract-transactions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["extraction"]["parser_name"] == "chase"
    assert payload["transactions"][0]["transaction_detail"] == "PAYROLL ACME INC"


def test_supported_institution_without_rows_returns_review_status(client: TestClient) -> None:
    stored_file = upload_file(
        client,
        "capital-one.pdf",
        """
        Capital One Bank
        Credit Card Account Summary
        Statement Period 08/11/2026 to 09/08/2026
        Account Number: XXXX1234
        New Balance
        """,
    )
    statement = detect_statement(client, stored_file["id"])

    response = client.post(f"/api/statements/{statement['id']}/extract-transactions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["extraction"]["parser_name"] == "capital-one"
    assert payload["extraction"]["status"] == "NEEDS_REVIEW"
    assert payload["transactions"] == []


def test_extraction_is_idempotent_and_does_not_duplicate_rows(client: TestClient) -> None:
    stored_file = upload_file(client, "chase-transactions.pdf", CHASE_TRANSACTION_TEXT)
    statement = detect_statement(client, stored_file["id"])

    first = client.post(f"/api/statements/{statement['id']}/extract-transactions")
    second = client.post(f"/api/statements/{statement['id']}/extract-transactions")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(first.json()["transactions"]) == 5
    assert len(second.json()["transactions"]) == 5


def test_extraction_count_remains_source_count_when_an_extracted_row_is_excluded(client: TestClient) -> None:
    stored_file = upload_file(client, "chase-transactions.pdf", CHASE_TRANSACTION_TEXT)
    statement = detect_statement(client, stored_file["id"])
    extracted = client.post(f"/api/statements/{statement['id']}/extract-transactions")
    assert extracted.status_code == 200, extracted.text

    excluded = client.delete(f"/api/transactions/{extracted.json()['transactions'][0]['id']}")
    assert excluded.status_code == 200, excluded.text

    active = client.get(f"/api/statements/{statement['id']}/transactions")
    assert active.status_code == 200, active.text
    assert active.json()["latest_extraction"]["transaction_count"] == 5
    assert len(active.json()["transactions"]) == 4


def test_transaction_edit_preserves_original_values_and_persists(client: TestClient) -> None:
    stored_file = upload_file(client, "chase-transactions.pdf", CHASE_TRANSACTION_TEXT)
    statement = detect_statement(client, stored_file["id"])
    transactions = client.post(f"/api/statements/{statement['id']}/extract-transactions").json()["transactions"]
    target = transactions[2]

    response = client.patch(
        f"/api/transactions/{target['id']}",
        json={"amount": "46.29", "transaction_detail": "CHEVRON CORRECTED", "direction": "OUTFLOW"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert amount(payload["amount"]) == Decimal("46.29")
    assert payload["transaction_detail"] == "CHEVRON CORRECTED"
    assert payload["user_edited"] is True
    assert amount(payload["original_amount"]) == Decimal("64.29")
    assert payload["original_transaction_detail"] == "CHEVRON 0094821 FREMONT CA"

    lookup = client.get(f"/api/statements/{statement['id']}/transactions")
    assert lookup.status_code == 200
    saved = next(transaction for transaction in lookup.json()["transactions"] if transaction["id"] == target["id"])
    assert amount(saved["amount"]) == Decimal("46.29")


def test_manual_add_and_exclusion_persist_and_reextraction_protects_user_work(client: TestClient) -> None:
    stored_file = upload_file(client, "chase-transactions.pdf", CHASE_TRANSACTION_TEXT)
    statement = detect_statement(client, stored_file["id"])
    extracted = client.post(f"/api/statements/{statement['id']}/extract-transactions").json()["transactions"]
    edited = extracted[1]
    excluded = extracted[2]

    edit_response = client.patch(
        f"/api/transactions/{edited['id']}",
        json={"amount": "100.00", "transaction_detail": "AMAZON CORRECTED", "direction": "OUTFLOW"},
    )
    add_response = client.post(
        f"/api/statements/{statement['id']}/transactions",
        json={
            "transaction_date": "2026-08-27",
            "transaction_detail": "MISSING MANUAL TRANSACTION",
            "amount": "22.10",
            "direction": "OUTFLOW",
        },
    )
    exclude_response = client.delete(f"/api/transactions/{excluded['id']}")

    assert edit_response.status_code == 200, edit_response.text
    assert add_response.status_code == 201, add_response.text
    assert add_response.json()["user_added"] is True
    assert exclude_response.status_code == 200, exclude_response.text
    assert exclude_response.json()["excluded"] is True

    reextracted = client.post(f"/api/statements/{statement['id']}/extract-transactions")

    assert reextracted.status_code == 200
    transactions = reextracted.json()["transactions"]
    details = [transaction["transaction_detail"] for transaction in transactions]
    assert "AMAZON CORRECTED" in details
    assert "MISSING MANUAL TRANSACTION" in details
    assert "CHEVRON 0094821 FREMONT CA" not in details
    assert len(transactions) == 5

    lookup = client.get(f"/api/statements/{statement['id']}/transactions?include_excluded=true")
    all_rows = lookup.json()["transactions"]
    excluded_rows = [transaction for transaction in all_rows if transaction["excluded"]]
    assert len(excluded_rows) == 1
    assert excluded_rows[0]["original_transaction_detail"] == "CHEVRON 0094821 FREMONT CA"


def test_transaction_edit_validation_rejects_bad_values(client: TestClient) -> None:
    stored_file = upload_file(client, "chase-transactions.pdf", CHASE_TRANSACTION_TEXT)
    statement = detect_statement(client, stored_file["id"])
    transaction = client.post(f"/api/statements/{statement['id']}/extract-transactions").json()["transactions"][0]

    invalid_amount = client.patch(f"/api/transactions/{transaction['id']}", json={"amount": "abc"})
    invalid_detail = client.patch(f"/api/transactions/{transaction['id']}", json={"transaction_detail": "   "})

    assert invalid_amount.status_code == 422
    assert invalid_detail.status_code == 422


def test_transaction_extraction_rejects_missing_physical_file(client: TestClient) -> None:
    from app.core.config import get_settings

    stored_file = upload_file(client, "chase-transactions.pdf", CHASE_TRANSACTION_TEXT)
    statement = detect_statement(client, stored_file["id"])
    physical_path = Path(get_settings().storage_dir) / stored_file["stored_filename"]
    physical_path.unlink()

    response = client.post(f"/api/statements/{statement['id']}/extract-transactions")

    assert response.status_code == 404
    assert response.json()["detail"] == "Stored file is missing."
