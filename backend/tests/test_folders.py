from fastapi.testclient import TestClient


def create_folder(client: TestClient, name: str, parent_folder_id: int | None = None) -> dict:
    response = client.post(
        "/api/folders",
        json={"name": name, "parent_folder_id": parent_folder_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_root_child_and_deeply_nested_folders(client: TestClient) -> None:
    root = create_folder(client, "2026")
    child = create_folder(client, "Bank Statements", root["id"])
    grandchild = create_folder(client, "Chase", child["id"])
    great_grandchild = create_folder(client, "Checking", grandchild["id"])

    assert root["parent_folder_id"] is None
    assert child["parent_folder_id"] == root["id"]
    assert grandchild["parent_folder_id"] == child["id"]
    assert great_grandchild["parent_folder_id"] == grandchild["id"]


def test_rename_folder(client: TestClient) -> None:
    folder = create_folder(client, "Old")

    response = client.patch(f"/api/folders/{folder['id']}", json={"name": "New"})

    assert response.status_code == 200
    assert response.json()["name"] == "New"


def test_move_folder(client: TestClient) -> None:
    destination = create_folder(client, "Destination")
    folder = create_folder(client, "Move Me")

    response = client.patch(
        f"/api/folders/{folder['id']}",
        json={"parent_folder_id": destination["id"]},
    )

    assert response.status_code == 200
    assert response.json()["parent_folder_id"] == destination["id"]


def test_delete_folder_removes_nested_folder(client: TestClient) -> None:
    parent = create_folder(client, "Parent")
    create_folder(client, "Child", parent["id"])

    response = client.delete(f"/api/folders/{parent['id']}")

    assert response.status_code == 204
    tree = client.get("/api/file-manager/tree").json()
    assert tree["folders"] == []


def test_reject_invalid_parent_folder(client: TestClient) -> None:
    response = client.post("/api/folders", json={"name": "Bad Parent", "parent_folder_id": 999})

    assert response.status_code == 404
    assert response.json()["detail"] == "Folder not found."


def test_reject_moving_folder_into_itself(client: TestClient) -> None:
    folder = create_folder(client, "Self")

    response = client.patch(
        f"/api/folders/{folder['id']}",
        json={"parent_folder_id": folder["id"]},
    )

    assert response.status_code == 400
    assert "itself" in response.json()["detail"]


def test_reject_moving_folder_into_descendant(client: TestClient) -> None:
    parent = create_folder(client, "Parent")
    child = create_folder(client, "Child", parent["id"])
    grandchild = create_folder(client, "Grandchild", child["id"])

    response = client.patch(
        f"/api/folders/{parent['id']}",
        json={"parent_folder_id": grandchild["id"]},
    )

    assert response.status_code == 400
    assert "descendant" in response.json()["detail"]


def test_reject_duplicate_folder_names_in_same_parent(client: TestClient) -> None:
    parent = create_folder(client, "Parent")
    create_folder(client, "Statements", parent["id"])

    response = client.post(
        "/api/folders",
        json={"name": "Statements", "parent_folder_id": parent["id"]},
    )

    assert response.status_code == 409
