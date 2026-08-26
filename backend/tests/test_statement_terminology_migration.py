from datetime import date
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.file import StoredFile
from app.models.statement import Statement
from app.models.transaction import CategoryRule, Transaction


def test_migration_preserves_selection_audits_categories_and_deactivates_invalid_rules(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    from app.core.config import get_settings

    get_settings.cache_clear()
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with Session(engine) as session:
        stored_file = StoredFile(
            original_filename="migration.pdf",
            display_name="migration.pdf",
            stored_filename="migration.pdf",
            storage_path="migration.pdf",
            mime_type="application/pdf",
            file_size=10,
        )
        session.add(stored_file)
        session.flush()
        statement = Statement(
            file_id=stored_file.id,
            document_type="BANK_STATEMENT",
            institution="CHASE",
            account_type="CHECKING",
        )
        session.add(statement)
        session.flush()
        transaction = Transaction(
            statement_id=statement.id,
            transaction_date=date(2026, 8, 1),
            transaction_detail="OLD RETAIL PURCHASE",
            amount=Decimal("12.34"),
            direction="OUTFLOW",
            source_order=1,
            transaction_type="EXPENSE",
            main_category="PERSONAL_INTERNAL",
            subcategory="UNCATEGORIZED",
            category_confidence=0.2,
            category_source="UNRESOLVED",
            category_status="NEEDS_REVIEW",
            user_edited_category=True,
            include_in_expenses=False,
            inclusion_initialized=True,
            inclusion_source="USER_EXCLUDED",
        )
        rule = CategoryRule(
            pattern="OLD RETAIL",
            main_category="PERSONAL_INTERNAL",
            subcategory="UNCATEGORIZED",
            match_type="PREFIX",
        )
        session.add_all([transaction, rule])
        session.commit()
        transaction_id = transaction.id
        rule_id = rule.id

    command.downgrade(config, "202608250010")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        migrated = connection.execute(
            text(
                """
                SELECT main_category, subcategory, category_status,
                       original_main_category, original_subcategory,
                       include_in_expenses, inclusion_source
                FROM transactions WHERE id = :transaction_id
                """
            ),
            {"transaction_id": transaction_id},
        ).mappings().one()
        active = connection.execute(
            text("SELECT active FROM category_rules WHERE id = :rule_id"),
            {"rule_id": rule_id},
        ).scalar_one()
        term_count = connection.execute(text("SELECT COUNT(*) FROM statement_terms")).scalar_one()

    assert migrated["main_category"] == "PROFIT_LOSS_BUSINESS"
    assert migrated["subcategory"] == "BUSINESS_OTHER_SUPPLIES"
    assert migrated["category_status"] == "NEEDS_REVIEW"
    assert migrated["original_main_category"] == "PERSONAL_INTERNAL"
    assert migrated["original_subcategory"] == "UNCATEGORIZED"
    assert migrated["include_in_expenses"] == 0
    assert migrated["inclusion_source"] == "USER_EXCLUDED"
    assert active == 0
    assert term_count >= 15
