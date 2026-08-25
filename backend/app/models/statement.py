from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class Statement(Base):
    __tablename__ = "statements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        unique=True,
    )
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    institution: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_type: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    account_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    statement_start_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    statement_end_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    detected_document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_institution: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detected_account_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_account_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    detected_statement_start_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    detected_statement_end_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    original_document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_institution: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_account_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_account_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    original_statement_start_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    original_statement_end_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    original_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_source: Mapped[str] = mapped_column(String(32), nullable=False, default="DETECTED")
    user_corrected: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    manual_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detection_confidence: Mapped[float] = mapped_column(Float(), nullable=False, default=0.0)
    detection_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_ANALYZED")
    detection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    file: Mapped[StoredFile] = relationship("StoredFile", back_populates="statement")
    transaction_extractions: Mapped[list[TransactionExtraction]] = relationship(
        "TransactionExtraction",
        back_populates="statement",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction",
        back_populates="statement",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


from app.models.file import StoredFile  # noqa: E402
from app.models.transaction import Transaction, TransactionExtraction  # noqa: E402
