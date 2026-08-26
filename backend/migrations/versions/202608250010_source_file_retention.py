"""source file retention fields

Revision ID: 202608250010
Revises: 202608240009
Create Date: 2026-08-25 21:15:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608250010"
down_revision: str | None = "202608240009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("source_file_available", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column("files", sa.Column("source_file_removed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("files", sa.Column("source_file_removal_reason", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("files", "source_file_removal_reason")
    op.drop_column("files", "source_file_removed_at")
    op.drop_column("files", "source_file_available")
