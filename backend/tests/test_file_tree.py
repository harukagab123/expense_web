from fastapi.testclient import TestClient


def create_folder(client: TestClient, name: str, parent_folder_id: int | None = None) -> dict:
    response = client.post(
        "/api/folders",
        json={"name": name, "parent_folder_id": parent_folder_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload_file(client: TestClient, filename: str, folder_id: int | None = None) -> dict:
    data = {} if folder_id is None else {"folder_id": str(folder_id)}
    response = client.post(
        "/api/files",
        data=data,
        files=[("files", (filename, f"%PDF-1.4\n{filename}\n%%EOF".encode(), "application/pdf"))],
    )
    assert response.status_code == 200, response.text
    return response.json()["uploaded"][0]["file"]


def test_tree_returns_nested_folders_and_files(client: TestClient) -> None:
    year = create_folder(client, "2026")
    bank = create_folder(client, "Bank Statements", year["id"])
    chase = create_folder(client, "Chase", bank["id"])
    upload_file(client, "January.pdf", chase["id"])
    upload_file(client, "Root.pdf")

    response = client.get("/api/file-manager/tree")

    assert response.status_code == 200
    tree = response.json()
    assert tree["name"] == "My Files"
    assert tree["files"][0]["display_name"] == "Root.pdf"
    assert tree["folders"][0]["name"] == "2026"
    assert tree["folders"][0]["folders"][0]["name"] == "Bank Statements"
    assert tree["folders"][0]["folders"][0]["folders"][0]["name"] == "Chase"
    assert tree["folders"][0]["folders"][0]["folders"][0]["files"][0]["display_name"] == "January.pdf"


def test_tree_search_keeps_hierarchy_for_matches(client: TestClient) -> None:
    year = create_folder(client, "2026")
    bank = create_folder(client, "Bank Statements", year["id"])
    chase = create_folder(client, "Chase", bank["id"])
    create_folder(client, "Capital One", bank["id"])
    upload_file(client, "January.pdf", chase["id"])

    response = client.get("/api/file-manager/tree?search=Chase")

    assert response.status_code == 200
    tree = response.json()
    assert tree["folders"][0]["name"] == "2026"
    bank_node = tree["folders"][0]["folders"][0]
    assert bank_node["name"] == "Bank Statements"
    assert [folder["name"] for folder in bank_node["folders"]] == ["Chase"]


def test_tree_sorting_keeps_items_within_their_parent(client: TestClient) -> None:
    parent = create_folder(client, "Parent")
    create_folder(client, "Beta", parent["id"])
    create_folder(client, "Alpha", parent["id"])
    upload_file(client, "b.pdf", parent["id"])
    upload_file(client, "a.pdf", parent["id"])

    response = client.get("/api/file-manager/tree?sort_by=name&sort_direction=asc")

    assert response.status_code == 200
    parent_node = response.json()["folders"][0]
    assert [folder["name"] for folder in parent_node["folders"]] == ["Alpha", "Beta"]
    assert [file["display_name"] for file in parent_node["files"]] == ["a.pdf", "b.pdf"]


def test_search_returns_flat_results_with_paths_and_expansion_ids(client: TestClient) -> None:
    year = create_folder(client, "2026")
    bank = create_folder(client, "Bank Statements", year["id"])
    chase = create_folder(client, "Chase", bank["id"])
    upload_file(client, "Chase January.pdf", chase["id"])
    upload_file(client, "Chase Root.pdf")

    response = client.get("/api/file-manager/search?query=Chase")

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "Chase"

    folder_result = next(result for result in payload["results"] if result["type"] == "folder")
    assert folder_result["name"] == "Chase"
    assert folder_result["parent_path"] == ["My Files", "2026", "Bank Statements"]
    assert folder_result["expand_folder_ids"] == [year["id"], bank["id"], chase["id"]]
    assert folder_result["parent_folder_id"] == bank["id"]

    file_result = next(result for result in payload["results"] if result["name"] == "Chase January.pdf")
    assert file_result["type"] == "file"
    assert file_result["parent_path"] == ["My Files", "2026", "Bank Statements", "Chase"]
    assert file_result["expand_folder_ids"] == [year["id"], bank["id"], chase["id"]]
    assert file_result["folder_id"] == chase["id"]
    assert file_result["mime_type"] == "application/pdf"


def test_search_empty_and_no_match_return_empty_results(client: TestClient) -> None:
    create_folder(client, "Bank Statements")
    upload_file(client, "January.pdf")

    empty_response = client.get("/api/file-manager/search?query=")
    missing_response = client.get("/api/file-manager/search?query=does-not-exist")

    assert empty_response.status_code == 200
    assert empty_response.json() == {"query": "", "results": []}
    assert missing_response.status_code == 200
    assert missing_response.json()["results"] == []
