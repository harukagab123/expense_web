"""transaction type detection

Revision ID: 202608240007
Revises: 202608240006
Create Date: 2026-08-24 19:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608240007"
down_revision: str | None = "202608240006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transaction_type_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.Column("transaction_type", sa.String(length=64), nullable=False),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("times_confirmed", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pattern", "match_type", name="uq_transaction_type_rule_pattern_type"),
    )

    op.add_column(
        "transactions",
        sa.Column("transaction_type", sa.String(length=64), server_default="UNKNOWN", nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("type_confidence", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("type_source", sa.String(length=32), server_default="UNRESOLVED", nullable=False),
    )
    op.add_column(
        "transactions",
        sa.Column("type_status", sa.String(length=64), server_default="NOT_CLASSIFIED", nullable=False),
    )
    op.add_column("transactions", sa.Column("type_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("suggested_include", sa.String(length=16), server_default="REVIEW", nullable=False),
    )
    op.add_column("transactions", sa.Column("original_transaction_type", sa.String(length=64), nullable=True))
    op.add_column("transactions", sa.Column("original_type_confidence", sa.Float(), nullable=True))
    op.add_column("transactions", sa.Column("original_type_source", sa.String(length=32), nullable=True))
    op.add_column("transactions", sa.Column("original_type_status", sa.String(length=64), nullable=True))
    op.add_column("transactions", sa.Column("original_suggested_include", sa.String(length=16), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("user_edited_type", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("transactions", sa.Column("type_rule_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_transactions_type_rule_id"), "transactions", ["type_rule_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_transactions_type_rule_id"), table_name="transactions")
    op.drop_column("transactions", "type_rule_id")
    op.drop_column("transactions", "user_edited_type")
    op.drop_column("transactions", "original_suggested_include")
    op.drop_column("transactions", "original_type_status")
    op.drop_column("transactions", "original_type_source")
    op.drop_column("transactions", "original_type_confidence")
    op.drop_column("transactions", "original_transaction_type")
    op.drop_column("transactions", "suggested_include")
    op.drop_column("transactions", "type_updated_at")
    op.drop_column("transactions", "type_status")
    op.drop_column("transactions", "type_source")
    op.drop_column("transactions", "type_confidence")
    op.drop_column("transactions", "transaction_type")
    op.drop_table("transaction_type_rules")
