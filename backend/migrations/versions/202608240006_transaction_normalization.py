"""transaction normalization

Revision ID: 202608240006
Revises: 202608240005
Create Date: 2026-08-24 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608240006"
down_revision: str | None = "202608240005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "merchant_normalization_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("times_confirmed", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pattern", "match_type", name="uq_merchant_normalization_rule_pattern_type"),
    )

    op.add_column("transactions", sa.Column("normalized_name", sa.String(length=255), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("normalization_confidence", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("normalization_source", sa.String(length=32), server_default="UNRESOLVED", nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("normalization_status", sa.String(length=64), server_default="NOT_NORMALIZED", nullable=False),
    )
    op.add_column("transactions", sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("transactions", sa.Column("original_normalized_name", sa.String(length=255), nullable=True))
    op.add_column("transactions", sa.Column("original_normalization_confidence", sa.Float(), nullable=True))
    op.add_column("transactions", sa.Column("original_normalization_source", sa.String(length=32), nullable=True))
    op.add_column("transactions", sa.Column("original_normalization_status", sa.String(length=64), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("user_edited_normalization", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("transactions", sa.Column("normalization_rule_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_transactions_normalization_rule_id"), "transactions", ["normalization_rule_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_transactions_normalization_rule_id"), table_name="transactions")
    op.drop_column("transactions", "normalization_rule_id")
    op.drop_column("transactions", "user_edited_normalization")
    op.drop_column("transactions", "original_normalization_status")
    op.drop_column("transactions", "original_normalization_source")
    op.drop_column("transactions", "original_normalization_confidence")
    op.drop_column("transactions", "original_normalized_name")
    op.drop_column("transactions", "normalized_at")
    op.drop_column("transactions", "normalization_status")
    op.drop_column("transactions", "normalization_source")
    op.drop_column("transactions", "normalization_confidence")
    op.drop_column("transactions", "normalized_name")
    op.drop_table("merchant_normalization_rules")
