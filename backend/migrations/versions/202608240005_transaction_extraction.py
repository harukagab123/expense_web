"""transaction extraction

Revision ID: 202608240005
Revises: 202608240004
Create Date: 2026-08-24 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608240005"
down_revision: str | None = "202608240004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transaction_extractions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("statement_id", sa.Integer(), nullable=False),
        sa.Column("parser_name", sa.String(length=120), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["statement_id"], ["statements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_transaction_extractions_statement_id"),
        "transaction_extractions",
        ["statement_id"],
        unique=False,
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("statement_id", sa.Integer(), nullable=False),
        sa.Column("extraction_id", sa.Integer(), nullable=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("transaction_detail", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("direction", sa.String(length=24), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("user_edited", sa.Boolean(), nullable=False),
        sa.Column("user_added", sa.Boolean(), nullable=False),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("original_transaction_date", sa.Date(), nullable=True),
        sa.Column("original_transaction_detail", sa.Text(), nullable=True),
        sa.Column("original_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("original_direction", sa.String(length=24), nullable=True),
        sa.Column("original_source_page", sa.Integer(), nullable=True),
        sa.Column("original_source_order", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["extraction_id"], ["transaction_extractions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["statement_id"], ["statements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transactions_extraction_id"), "transactions", ["extraction_id"], unique=False)
    op.create_index(op.f("ix_transactions_statement_id"), "transactions", ["statement_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_transactions_statement_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_extraction_id"), table_name="transactions")
    op.drop_table("transactions")
    op.drop_index(op.f("ix_transaction_extractions_statement_id"), table_name="transaction_extractions")
    op.drop_table("transaction_extractions")
