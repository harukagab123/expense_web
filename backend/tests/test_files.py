from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings


def create_folder(client: TestClient, name: str, parent_folder_id: int | None = None) -> dict:
    response = client.post(
        "/api/folders",
        json={"name": name, "parent_folder_id": parent_folder_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload_file(
    client: TestClient,
    filename: str,
    content: bytes,
    content_type: str,
    folder_id: int | None = None,
) -> dict:
    data = {} if folder_id is None else {"folder_id": str(folder_id)}
    response = client.post(
        "/api/files",
        data=data,
        files=[("files", (filename, content, content_type))],
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["failed"] == []
    assert len(payload["uploaded"]) == 1
    return payload["uploaded"][0]["file"]


def test_upload_file_preserves_display_name_and_uses_unique_storage_name(client: TestClient) -> None:
    folder = create_folder(client, "Uploads")

    first = upload_file(client, "Chase.pdf", b"%PDF-1.4\n%%EOF", "application/pdf", folder["id"])
    second = upload_file(client, "Capital One.pdf", b"%PDF-1.4\nCapital One\n%%EOF", "application/pdf", folder["id"])

    assert first["display_name"] == "Chase.pdf"
    assert first["original_filename"] == "Chase.pdf"
    assert first["stored_filename"] != "Chase.pdf"
    assert first["stored_filename"] != second["stored_filename"]


def test_upload_multiple_files_reports_successes_and_failures(client: TestClient) -> None:
    folder = create_folder(client, "Uploads")

    response = client.post(
        "/api/files",
        data={"folder_id": str(folder["id"])},
        files=[
            ("files", ("January.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")),
            ("files", ("script.exe", b"nope", "application/octet-stream")),
            ("files", ("notes.txt", b"hello", "text/plain")),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["filename"] for item in payload["uploaded"]] == ["January.pdf", "notes.txt"]
    assert payload["failed"] == [{"filename": "script.exe", "error": "Unsupported file type."}]


def test_reject_duplicate_display_filename_in_same_folder(client: TestClient) -> None:
    folder = create_folder(client, "Uploads")
    upload_file(client, "Chase.pdf", b"%PDF-1.4\n%%EOF", "application/pdf", folder["id"])

    response = client.post(
        "/api/files",
        data={"folder_id": str(folder["id"])},
        files=[("files", ("Chase.pdf", b"%PDF-1.4\n%%EOF", "application/pdf"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["uploaded"] == []
    assert payload["failed"][0]["error"] == "A file with that name already exists here."


def test_rename_file_display_name_without_renaming_physical_file(client: TestClient) -> None:
    stored_file = upload_file(client, "Chase.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")
    original_stored_filename = stored_file["stored_filename"]

    response = client.patch(
        f"/api/files/{stored_file['id']}",
        json={"display_name": "Chase Checking.pdf"},
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Chase Checking.pdf"
    assert response.json()["stored_filename"] == original_stored_filename


def test_move_file(client: TestClient) -> None:
    destination = create_folder(client, "Bank Statements")
    stored_file = upload_file(client, "Chase.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")

    response = client.patch(f"/api/files/{stored_file['id']}", json={"folder_id": destination["id"]})

    assert response.status_code == 200
    assert response.json()["folder_id"] == destination["id"]


def test_download_file(client: TestClient) -> None:
    stored_file = upload_file(client, "notes.txt", b"hello", "text/plain")

    response = client.get(f"/api/files/{stored_file['id']}/download")

    assert response.status_code == 200
    assert response.content == b"hello"
    assert "notes.txt" in response.headers["content-disposition"]


def test_preview_pdf_and_image_files(client: TestClient) -> None:
    pdf = upload_file(client, "January.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")
    png = upload_file(client, "statement.png", b"\x89PNG\r\n\x1a\n", "image/png")
    jpg = upload_file(client, "statement.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")

    pdf_response = client.get(f"/api/files/{pdf['id']}/preview")
    png_response = client.get(f"/api/files/{png['id']}/preview")
    jpg_response = client.get(f"/api/files/{jpg['id']}/preview")

    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert pdf_response.headers["content-disposition"].startswith("inline")
    assert png_response.status_code == 200
    assert png_response.headers["content-type"].startswith("image/png")
    assert jpg_response.status_code == 200
    assert jpg_response.headers["content-type"].startswith("image/jpeg")


def test_unsupported_preview_returns_clear_error(client: TestClient) -> None:
    stored_file = upload_file(client, "notes.txt", b"hello", "text/plain")

    response = client.get(f"/api/files/{stored_file['id']}/preview")

    assert response.status_code == 415
    assert response.json()["detail"] == "Preview is not supported for this file type."
    assert stored_file["stored_filename"] not in response.text


def test_missing_physical_file_preview_returns_clear_error_without_storage_path(client: TestClient) -> None:
    stored_file = upload_file(client, "January.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")
    physical_path = Path(get_settings().storage_dir) / stored_file["stored_filename"]
    physical_path.unlink()

    response = client.get(f"/api/files/{stored_file['id']}/preview")

    assert response.status_code == 404
    assert response.json()["detail"] == "Stored file is missing."
    assert stored_file["stored_filename"] not in response.text


def test_delete_file_removes_database_record_and_physical_file(client: TestClient) -> None:
    stored_file = upload_file(client, "notes.txt", b"hello", "text/plain")
    physical_path = Path(get_settings().storage_dir) / stored_file["stored_filename"]
    assert physical_path.exists()

    response = client.delete(f"/api/files/{stored_file['id']}")

    assert response.status_code == 204
    assert not physical_path.exists()
    assert client.delete(f"/api/files/{stored_file['id']}").status_code == 404


def test_reject_path_traversal_filename(client: TestClient) -> None:
    response = client.post(
        "/api/files",
        files=[("files", ("../evil.txt", b"bad", "text/plain"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["uploaded"] == []
    assert payload["failed"][0]["error"] == "Filename cannot contain path separators."


def test_invalid_file_and_folder_ids_return_clear_errors(client: TestClient) -> None:
    stored_file = upload_file(client, "notes.txt", b"hello", "text/plain")

    invalid_file_response = client.patch("/api/files/999", json={"display_name": "missing.txt"})
    invalid_folder_response = client.patch(f"/api/files/{stored_file['id']}", json={"folder_id": 999})

    assert invalid_file_response.status_code == 404
    assert invalid_file_response.json()["detail"] == "File not found."
    assert invalid_folder_response.status_code == 404
    assert invalid_folder_response.json()["detail"] == "Folder not found."


def test_reject_oversized_file(client: TestClient, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("MAX_UPLOAD_BYTES", "3")
    get_settings.cache_clear()

    response = client.post(
        "/api/files",
        files=[("files", ("big.txt", b"too large", "text/plain"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["uploaded"] == []
    assert payload["failed"][0]["error"] == "File exceeds the configured upload size limit."
