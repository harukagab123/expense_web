"""expense categorization

Revision ID: 202608240008
Revises: 202608240007
Create Date: 2026-08-24 20:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608240008"
down_revision: str | None = "202608240007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "category_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.Column("main_category", sa.String(length=64), nullable=False),
        sa.Column("subcategory", sa.String(length=64), nullable=False),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("times_confirmed", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pattern", "match_type", name="uq_category_rule_pattern_type"),
    )

    op.add_column("transactions", sa.Column("main_category", sa.String(length=64), nullable=True))
    op.add_column("transactions", sa.Column("subcategory", sa.String(length=64), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("category_confidence", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("category_source", sa.String(length=32), server_default="UNRESOLVED", nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("category_status", sa.String(length=64), server_default="NOT_CATEGORIZED", nullable=False),
    )
    op.add_column("transactions", sa.Column("category_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("transactions", sa.Column("original_main_category", sa.String(length=64), nullable=True))
    op.add_column("transactions", sa.Column("original_subcategory", sa.String(length=64), nullable=True))
    op.add_column("transactions", sa.Column("original_category_confidence", sa.Float(), nullable=True))
    op.add_column("transactions", sa.Column("original_category_source", sa.String(length=32), nullable=True))
    op.add_column("transactions", sa.Column("original_category_status", sa.String(length=64), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("user_edited_category", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("transactions", sa.Column("category_rule_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_transactions_category_rule_id"), "transactions", ["category_rule_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_transactions_category_rule_id"), table_name="transactions")
    op.drop_column("transactions", "category_rule_id")
    op.drop_column("transactions", "user_edited_category")
    op.drop_column("transactions", "original_category_status")
    op.drop_column("transactions", "original_category_source")
    op.drop_column("transactions", "original_category_confidence")
    op.drop_column("transactions", "original_subcategory")
    op.drop_column("transactions", "original_main_category")
    op.drop_column("transactions", "category_updated_at")
    op.drop_column("transactions", "category_status")
    op.drop_column("transactions", "category_source")
    op.drop_column("transactions", "category_confidence")
    op.drop_column("transactions", "subcategory")
    op.drop_column("transactions", "main_category")
    op.drop_table("category_rules")
