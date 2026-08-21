from fastapi.testclient import TestClient


def test_root_endpoint_works() -> None:
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Personal Financial File Manager",
        "status": "running",
    }


def test_health_endpoint_reports_database_status(temp_database_url: str) -> None:
    assert temp_database_url.startswith("sqlite:///")

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_database_health_endpoint_reports_database_status(temp_database_url: str) -> None:
    assert temp_database_url.startswith("sqlite:///")

    from app.main import app

    with TestClient(app) as client:
        response = client.get("/api/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
