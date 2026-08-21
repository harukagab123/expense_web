from sqlalchemy import text

from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.models.infrastructure import InfrastructureCheck


def test_database_connection_works(temp_database_url: str) -> None:
    assert temp_database_url.startswith("sqlite:///")

    with get_engine().connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar_one()

    assert result == 1


def test_database_write_and_read_works(temp_database_url: str) -> None:
    assert temp_database_url.startswith("sqlite:///")

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    session_factory = get_session_factory()

    with session_factory() as session:
        check = InfrastructureCheck(message="phase-1-test")
        session.add(check)
        session.commit()
        session.refresh(check)
        check_id = check.id

    with session_factory() as session:
        stored = session.get(InfrastructureCheck, check_id)

    assert stored is not None
    assert stored.message == "phase-1-test"
