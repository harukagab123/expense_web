"""statement terminology intelligence and category cleanup

Revision ID: 202608260011
Revises: 202608250010
Create Date: 2026-08-26 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608260011"
down_revision: str | None = "202608250010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEED_TERMS = (
    ("PRK", "Parking", "GLOBAL", "GARAGE|METER|CITY", 0.80),
    ("PRK", "Parking", "CHASE", "GARAGE|METER|CITY", 0.87),
    ("PMT", "Payment", "GLOBAL", "ANY", 0.86),
    ("PYMT", "Payment", "GLOBAL", "ANY", 0.86),
    ("PAYMNT", "Payment", "GLOBAL", "ANY", 0.88),
    ("AUTO PMT", "Automatic Payment", "GLOBAL", "ANY", 0.96),
    ("AUTOPAY", "Automatic Payment", "GLOBAL", "ANY", 0.96),
    ("ACH PMT", "ACH Payment", "GLOBAL", "ANY", 0.97),
    ("ACH", "Automated Clearing House", "GLOBAL", "ANY", 0.90),
    ("POS", "Point of Sale", "GLOBAL", "ANY", 0.86),
    ("DBT", "Debit", "GLOBAL", "ANY", 0.84),
    ("CRD", "Card", "GLOBAL", "ANY", 0.84),
    ("AMZN", "Amazon", "GLOBAL", "ANY", 0.97),
    ("MKTPL", "Marketplace", "GLOBAL", "ANY", 0.96),
    ("WHSE", "Warehouse", "GLOBAL", "ANY", 0.94),
    ("AMEX", "American Express", "GLOBAL", "ANY", 0.97),
)


def upgrade() -> None:
    op.add_column("category_rules", sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("transactions", sa.Column("interpreted_detail", sa.Text(), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("terminology_confidence", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column("transactions", sa.Column("terminology_matches", sa.Text(), nullable=True))
    op.add_column("transactions", sa.Column("terminology_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "statement_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("term", sa.String(length=120), nullable=False),
        sa.Column("normalized_meaning", sa.String(length=255), nullable=False),
        sa.Column("institution", sa.String(length=64), server_default="GLOBAL", nullable=False),
        sa.Column("context", sa.String(length=255), server_default="ANY", nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("times_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("times_confirmed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=32), server_default="BUILT_IN", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("term", "institution", "context", name="uq_statement_term_scope_context"),
    )
    term_table = sa.table(
        "statement_terms",
        sa.column("term", sa.String),
        sa.column("normalized_meaning", sa.String),
        sa.column("institution", sa.String),
        sa.column("context", sa.String),
        sa.column("confidence", sa.Float),
        sa.column("times_seen", sa.Integer),
        sa.column("times_confirmed", sa.Integer),
        sa.column("source", sa.String),
    )
    op.bulk_insert(
        term_table,
        [
            {
                "term": term,
                "normalized_meaning": meaning,
                "institution": institution,
                "context": context,
                "confidence": confidence,
                "times_seen": 0,
                "times_confirmed": 0,
                "source": "BUILT_IN",
            }
            for term, meaning, institution, context, confidence in SEED_TERMS
        ],
    )

    removed_main = "main_category = 'PERSONAL_INTERNAL'"
    removed_sub = "subcategory IN ('PERSONAL_OTHER_ITEMS', 'PERSONAL', 'UNCATEGORIZED')"
    removed = f"({removed_main} OR {removed_sub})"
    op.execute(
        sa.text(
            f"""
            UPDATE transactions
            SET original_main_category = COALESCE(original_main_category, main_category),
                original_subcategory = COALESCE(original_subcategory, subcategory),
                original_category_confidence = COALESCE(original_category_confidence, category_confidence),
                original_category_source = COALESCE(original_category_source, category_source),
                original_category_status = COALESCE(original_category_status, category_status)
            WHERE {removed}
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE transactions
            SET main_category = NULL,
                subcategory = NULL,
                category_confidence = 1.0,
                category_source = 'UNRESOLVED',
                category_status = 'NOT_APPLICABLE',
                category_rule_id = NULL,
                user_edited_category = 0
            WHERE {removed}
              AND NOT (transaction_type IN ('EXPENSE', 'BANK_FEE') OR (transaction_type = 'INTEREST' AND direction = 'OUTFLOW'))
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE transactions
            SET main_category = CASE
                    WHEN UPPER(transaction_detail) LIKE '%PARKING%' THEN 'AUTO_EXPENSE'
                    WHEN UPPER(transaction_detail) LIKE '%CHEVRON%' OR UPPER(transaction_detail) LIKE '%COSTCO GAS%' THEN 'AUTO_EXPENSE'
                    WHEN UPPER(transaction_detail) LIKE '%COMCAST%' OR UPPER(transaction_detail) LIKE '%PG&E%' THEN 'BUSINESS_USE_OF_HOME'
                    ELSE 'PROFIT_LOSS_BUSINESS' END,
                subcategory = CASE
                    WHEN UPPER(transaction_detail) LIKE '%PARKING%' THEN 'AUTO_PARKING'
                    WHEN UPPER(transaction_detail) LIKE '%CHEVRON%' OR UPPER(transaction_detail) LIKE '%COSTCO GAS%' THEN 'AUTO_GAS'
                    WHEN UPPER(transaction_detail) LIKE '%COMCAST%' THEN 'HOME_TELECOM_INTERNET'
                    WHEN UPPER(transaction_detail) LIKE '%PG&E%' THEN 'HOME_UTILITIES'
                    ELSE 'BUSINESS_OTHER_SUPPLIES' END,
                category_confidence = 0.30,
                category_source = 'MIGRATION',
                category_status = 'NEEDS_REVIEW',
                category_rule_id = NULL,
                user_edited_category = 0
            WHERE {removed}
              AND (transaction_type IN ('EXPENSE', 'BANK_FEE') OR (transaction_type = 'INTEREST' AND direction = 'OUTFLOW'))
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE category_rules
            SET active = 0
            WHERE main_category = 'PERSONAL_INTERNAL'
               OR subcategory IN ('PERSONAL_OTHER_ITEMS', 'PERSONAL', 'UNCATEGORIZED')
            """
        )
    )


def downgrade() -> None:
    op.drop_table("statement_terms")
    op.drop_column("transactions", "terminology_updated_at")
    op.drop_column("transactions", "terminology_matches")
    op.drop_column("transactions", "terminology_confidence")
    op.drop_column("transactions", "interpreted_detail")
    op.drop_column("category_rules", "active")
