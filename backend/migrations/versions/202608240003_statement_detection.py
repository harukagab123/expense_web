"""statement detection metadata

Revision ID: 202608240003
Revises: 202608210002
Create Date: 2026-08-24 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608240003"
down_revision: str | None = "202608210002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "statements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=64), nullable=False),
        sa.Column("institution", sa.String(length=64), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=True),
        sa.Column("account_type", sa.String(length=64), nullable=False),
        sa.Column("account_last_four", sa.String(length=4), nullable=True),
        sa.Column("statement_start_date", sa.Date(), nullable=True),
        sa.Column("statement_end_date", sa.Date(), nullable=True),
        sa.Column("detection_confidence", sa.Float(), nullable=False),
        sa.Column("detection_status", sa.String(length=64), nullable=False),
        sa.Column("detection_reason", sa.String(length=500), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
    )
    op.create_index(op.f("ix_statements_file_id"), "statements", ["file_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_statements_file_id"), table_name="statements")
    op.drop_table("statements")
