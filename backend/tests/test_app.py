def test_application_imports_successfully() -> None:
    from app.main import app

    assert app.title == "Personal Financial File Manager"
