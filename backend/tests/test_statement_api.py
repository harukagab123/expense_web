from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings


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


def upload_file(
    client: TestClient,
    filename: str,
    content: bytes,
    content_type: str,
) -> dict:
    response = client.post(
        "/api/files",
        files=[("files", (filename, content, content_type))],
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["failed"] == []
    return payload["uploaded"][0]["file"]


def test_detect_statement_endpoint_persists_and_reanalyzes_without_duplicate(client: TestClient) -> None:
    stored_file = upload_file(
        client,
        "chase.pdf",
        make_pdf(
            """
            JPMorgan Chase Bank
            Chase Total Checking Statement
            Statement Period 08/11/2026 - 09/08/2026
            Account ending in 4205
            Beginning Balance
            Ending Balance
            Transaction Detail
            Capital One Mobile Pmt
            American Express ACH Pmt
            TJX Rewards Mastercard Payment
            """
        ),
        "application/pdf",
    )

    first = client.post(f"/api/files/{stored_file['id']}/detect-statement")
    lookup = client.get(f"/api/files/{stored_file['id']}/statement")
    second = client.post(f"/api/files/{stored_file['id']}/detect-statement")

    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["document_type"] == "BANK_STATEMENT"
    assert first_payload["institution"] == "CHASE"
    assert first_payload["account_type"] == "CHECKING"
    assert first_payload["account_last_four"] == "4205"
    assert first_payload["detected_institution"] == "CHASE"
    assert first_payload["original_institution"] == "CHASE"
    assert first_payload["metadata_source"] == "DETECTED"
    assert first_payload["user_corrected"] is False
    assert first_payload["statement_start_date"] == "2026-08-11"
    assert first_payload["statement_end_date"] == "2026-09-08"
    assert first_payload["detection_status"] == "DETECTED"
    assert first_payload["detection_confidence"] > 0.75
    assert lookup.status_code == 200
    assert lookup.json()["statement"]["id"] == first_payload["id"]
    assert second.status_code == 200
    assert second.json()["id"] == first_payload["id"]


def test_statement_edit_persists_current_metadata_and_preserves_detector_values(client: TestClient) -> None:
    stored_file = upload_file(
        client,
        "capital-one.pdf",
        make_pdf(
            """
            Capital One Bank
            Credit Card Account Summary
            Statement Period 08/11/2026 to 09/08/2026
            Account Number: XXXX1234
            Payment Due Date
            Minimum Payment
            New Balance
            """
        ),
        "application/pdf",
    )
    detected = client.post(f"/api/files/{stored_file['id']}/detect-statement").json()
    assert detected["institution"] == "CAPITAL_ONE"

    response = client.patch(
        f"/api/files/{stored_file['id']}/statement",
        json={
            "document_type": "BANK_STATEMENT",
            "institution": "CHASE",
            "product_name": "Everyday Checking",
            "account_type": "CHECKING",
            "account_last_four": "9876",
            "statement_start_date": "2026-08-01",
            "statement_end_date": "2026-08-31",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["document_type"] == "BANK_STATEMENT"
    assert payload["institution"] == "CHASE"
    assert payload["product_name"] == "Everyday Checking"
    assert payload["account_type"] == "CHECKING"
    assert payload["account_last_four"] == "9876"
    assert payload["statement_start_date"] == "2026-08-01"
    assert payload["statement_end_date"] == "2026-08-31"
    assert payload["metadata_source"] == "USER_EDITED"
    assert payload["user_corrected"] is True
    assert payload["manual_updated_at"] is not None
    assert payload["detected_institution"] == "CAPITAL_ONE"
    assert payload["original_institution"] == "CAPITAL_ONE"

    lookup = client.get(f"/api/files/{stored_file['id']}/statement")
    assert lookup.status_code == 200
    assert lookup.json()["statement"]["institution"] == "CHASE"


def test_statement_edit_rejects_full_account_number(client: TestClient) -> None:
    stored_file = upload_file(client, "chase.pdf", make_pdf("JPMorgan Chase Bank Statement"), "application/pdf")
    client.post(f"/api/files/{stored_file['id']}/detect-statement")

    response = client.patch(
        f"/api/files/{stored_file['id']}/statement",
        json={"account_last_four": "123456789"},
    )

    assert response.status_code == 422
    lookup = client.get(f"/api/files/{stored_file['id']}/statement")
    assert lookup.json()["statement"]["account_last_four"] != "123456789"


def test_statement_edit_rejects_invalid_date_range(client: TestClient) -> None:
    stored_file = upload_file(client, "chase.pdf", make_pdf("JPMorgan Chase Bank Statement"), "application/pdf")
    client.post(f"/api/files/{stored_file['id']}/detect-statement")

    response = client.patch(
        f"/api/files/{stored_file['id']}/statement",
        json={"statement_start_date": "2026-09-08", "statement_end_date": "2026-08-11"},
    )

    assert response.status_code == 422
    assert "Statement start date" in response.text


def test_reanalysis_preserves_user_correction_and_updates_latest_detection(client: TestClient) -> None:
    stored_file = upload_file(
        client,
        "capital-one.pdf",
        make_pdf(
            """
            Capital One Bank
            Credit Card Account Summary
            Statement Period 08/11/2026 to 09/08/2026
            Account Number: XXXX1234
            New Balance
            """
        ),
        "application/pdf",
    )
    detected = client.post(f"/api/files/{stored_file['id']}/detect-statement")
    assert detected.json()["institution"] == "CAPITAL_ONE"

    edited = client.patch(
        f"/api/files/{stored_file['id']}/statement",
        json={"institution": "CHASE", "account_type": "CHECKING"},
    )
    assert edited.status_code == 200
    assert edited.json()["institution"] == "CHASE"

    reanalyzed = client.post(f"/api/files/{stored_file['id']}/detect-statement")

    assert reanalyzed.status_code == 200
    payload = reanalyzed.json()
    assert payload["institution"] == "CHASE"
    assert payload["account_type"] == "CHECKING"
    assert payload["metadata_source"] == "USER_EDITED"
    assert payload["user_corrected"] is True
    assert payload["detected_institution"] == "CAPITAL_ONE"
    assert payload["original_institution"] == "CAPITAL_ONE"


def test_statement_lookup_returns_null_before_analysis(client: TestClient) -> None:
    stored_file = upload_file(client, "notes.pdf", make_pdf("Meeting Notes"), "application/pdf")

    response = client.get(f"/api/files/{stored_file['id']}/statement")

    assert response.status_code == 200
    assert response.json() == {"statement": None}


def test_detection_rejects_non_pdf_files(client: TestClient) -> None:
    stored_file = upload_file(client, "notes.txt", b"hello", "text/plain")

    response = client.post(f"/api/files/{stored_file['id']}/detect-statement")

    assert response.status_code == 415
    assert response.json()["detail"] == "Statement detection is available for PDF files only."


def test_detection_missing_physical_file_returns_safe_error(client: TestClient) -> None:
    stored_file = upload_file(client, "chase.pdf", make_pdf("JPMorgan Chase Bank Statement"), "application/pdf")
    physical_path = Path(get_settings().storage_dir) / stored_file["stored_filename"]
    physical_path.unlink()

    response = client.post(f"/api/files/{stored_file['id']}/detect-statement")

    assert response.status_code == 404
    assert response.json()["detail"] == "Stored file is missing."
    assert stored_file["stored_filename"] not in response.text


def test_detection_for_pdf_without_text_needs_review(client: TestClient) -> None:
    stored_file = upload_file(client, "blank.pdf", make_pdf(""), "application/pdf")

    response = client.post(f"/api/files/{stored_file['id']}/detect-statement")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_type"] == "UNKNOWN"
    assert payload["institution"] == "UNKNOWN"
    assert payload["detection_status"] == "NEEDS_REVIEW"
    assert payload["detection_reason"] == "No extractable PDF text found."


def test_detection_failure_stores_safe_failed_status(client: TestClient, monkeypatch) -> None:
    from app.services.statement_detection import service
    from app.services.statement_detection.pdf_text import PdfTextExtractionError

    stored_file = upload_file(client, "broken.pdf", make_pdf("JPMorgan Chase Bank Statement"), "application/pdf")

    def fail_extract(_):
        raise PdfTextExtractionError("private parser detail")

    monkeypatch.setattr(service, "extract_pdf_text", fail_extract)

    response = client.post(f"/api/files/{stored_file['id']}/detect-statement")

    assert response.status_code == 200
    payload = response.json()
    assert payload["detection_status"] == "FAILED"
    assert payload["detection_reason"] == "The PDF could not be read."
    assert "private parser detail" not in response.text
