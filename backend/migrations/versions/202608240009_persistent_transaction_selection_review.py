"""persistent transaction selection and review

Revision ID: 202608240009
Revises: 202608240008
Create Date: 2026-08-24 21:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608240009"
down_revision: str | None = "202608240008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("include_in_expenses", sa.Boolean(), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("inclusion_initialized", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("inclusion_source", sa.String(length=32), server_default="UNINITIALIZED", nullable=False),
    )
    op.add_column("transactions", sa.Column("inclusion_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("review_status", sa.String(length=32), server_default="PENDING", nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("review_source", sa.String(length=32), server_default="SYSTEM", nullable=False),
    )
    op.add_column("transactions", sa.Column("review_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE transactions
            SET
                include_in_expenses = 1,
                inclusion_initialized = 1,
                inclusion_source = 'INITIAL_DEFAULT',
                inclusion_updated_at = CURRENT_TIMESTAMP,
                review_status = CASE
                    WHEN needs_review = 1
                        OR normalization_status = 'NEEDS_REVIEW'
                        OR type_status = 'NEEDS_REVIEW'
                        OR transaction_type = 'UNKNOWN'
                        OR suggested_include = 'REVIEW'
                        OR category_status IN ('NEEDS_REVIEW', 'NOT_CATEGORIZED')
                        OR subcategory = 'UNCATEGORIZED'
                    THEN 'NEEDS_REVIEW'
                    ELSE 'PENDING'
                END,
                review_source = 'SYSTEM',
                review_updated_at = CURRENT_TIMESTAMP
            WHERE excluded = 0
                AND (inclusion_initialized = 0 OR include_in_expenses IS NULL)
            """
        )
    )


def downgrade() -> None:
    op.drop_column("transactions", "review_updated_at")
    op.drop_column("transactions", "review_source")
    op.drop_column("transactions", "review_status")
    op.drop_column("transactions", "inclusion_updated_at")
    op.drop_column("transactions", "inclusion_source")
    op.drop_column("transactions", "inclusion_initialized")
    op.drop_column("transactions", "include_in_expenses")
