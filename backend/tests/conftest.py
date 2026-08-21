from collections.abc import Iterator

import pytest


@pytest.fixture()
def temp_database_url(tmp_path, monkeypatch) -> Iterator[str]:
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    from app.core.config import get_settings
    from app.db.session import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    yield database_url

    get_session_factory.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()
