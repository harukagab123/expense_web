"""expense summary duplicate upload protection

Revision ID: 202608270012
Revises: 202608260011
Create Date: 2026-08-27 00:10:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608270012"
down_revision: str | None = "202608260011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("files", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    op.create_index("ix_files_content_sha256", "files", ["content_sha256"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_files_content_sha256", table_name="files")
    op.drop_column("files", "content_sha256")
