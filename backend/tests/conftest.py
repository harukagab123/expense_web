from collections.abc import Iterator

import pytest


@pytest.fixture()
def temp_database_url(tmp_path, monkeypatch) -> Iterator[str]:
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(1024 * 1024))

    from app.core.config import get_settings
    from app.db.session import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    yield database_url

    get_session_factory.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture()
def client(temp_database_url: str):
    assert temp_database_url.startswith("sqlite:///")

    from fastapi.testclient import TestClient

    from app.db.base import Base
    from app.db.session import get_engine
    from app.main import app

    Base.metadata.create_all(bind=get_engine())

    with TestClient(app) as test_client:
        yield test_client
