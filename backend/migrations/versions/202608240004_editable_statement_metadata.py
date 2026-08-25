"""editable statement metadata

Revision ID: 202608240004
Revises: 202608240003
Create Date: 2026-08-24 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "202608240004"
down_revision: str | None = "202608240003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("statements", sa.Column("detected_document_type", sa.String(length=64), nullable=True))
    op.add_column("statements", sa.Column("detected_institution", sa.String(length=64), nullable=True))
    op.add_column("statements", sa.Column("detected_product_name", sa.String(length=255), nullable=True))
    op.add_column("statements", sa.Column("detected_account_type", sa.String(length=64), nullable=True))
    op.add_column("statements", sa.Column("detected_account_last_four", sa.String(length=4), nullable=True))
    op.add_column("statements", sa.Column("detected_statement_start_date", sa.Date(), nullable=True))
    op.add_column("statements", sa.Column("detected_statement_end_date", sa.Date(), nullable=True))
    op.add_column("statements", sa.Column("original_document_type", sa.String(length=64), nullable=True))
    op.add_column("statements", sa.Column("original_institution", sa.String(length=64), nullable=True))
    op.add_column("statements", sa.Column("original_product_name", sa.String(length=255), nullable=True))
    op.add_column("statements", sa.Column("original_account_type", sa.String(length=64), nullable=True))
    op.add_column("statements", sa.Column("original_account_last_four", sa.String(length=4), nullable=True))
    op.add_column("statements", sa.Column("original_statement_start_date", sa.Date(), nullable=True))
    op.add_column("statements", sa.Column("original_statement_end_date", sa.Date(), nullable=True))
    op.add_column("statements", sa.Column("original_detected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "statements",
        sa.Column("metadata_source", sa.String(length=32), server_default="DETECTED", nullable=False),
    )
    op.add_column(
        "statements",
        sa.Column("user_corrected", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("statements", sa.Column("manual_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE statements
        SET detected_document_type = document_type,
            detected_institution = institution,
            detected_product_name = product_name,
            detected_account_type = account_type,
            detected_account_last_four = account_last_four,
            detected_statement_start_date = statement_start_date,
            detected_statement_end_date = statement_end_date,
            original_document_type = document_type,
            original_institution = institution,
            original_product_name = product_name,
            original_account_type = account_type,
            original_account_last_four = account_last_four,
            original_statement_start_date = statement_start_date,
            original_statement_end_date = statement_end_date,
            original_detected_at = detected_at
        """
    )


def downgrade() -> None:
    op.drop_column("statements", "manual_updated_at")
    op.drop_column("statements", "user_corrected")
    op.drop_column("statements", "metadata_source")
    op.drop_column("statements", "original_detected_at")
    op.drop_column("statements", "original_statement_end_date")
    op.drop_column("statements", "original_statement_start_date")
    op.drop_column("statements", "original_account_last_four")
    op.drop_column("statements", "original_account_type")
    op.drop_column("statements", "original_product_name")
    op.drop_column("statements", "original_institution")
    op.drop_column("statements", "original_document_type")
    op.drop_column("statements", "detected_statement_end_date")
    op.drop_column("statements", "detected_statement_start_date")
    op.drop_column("statements", "detected_account_last_four")
    op.drop_column("statements", "detected_account_type")
    op.drop_column("statements", "detected_product_name")
    op.drop_column("statements", "detected_institution")
    op.drop_column("statements", "detected_document_type")
