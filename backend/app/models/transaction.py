from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class TransactionExtraction(Base):
    __tablename__ = "transaction_extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("statements.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    parser_name: Mapped[str] = mapped_column(String(120), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_EXTRACTED")
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    statement: Mapped[Statement] = relationship("Statement", back_populates="transaction_extractions")
    transactions: Mapped[list[Transaction]] = relationship("Transaction", back_populates="extraction")


class MerchantNormalizationRule(Base):
    __tablename__ = "merchant_normalization_rules"
    __table_args__ = (UniqueConstraint("pattern", "match_type", name="uq_merchant_normalization_rule_pattern_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False, default="EXACT")
    times_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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

    transactions: Mapped[list[Transaction]] = relationship("Transaction", back_populates="normalization_rule")


class TransactionTypeRule(Base):
    __tablename__ = "transaction_type_rules"
    __table_args__ = (UniqueConstraint("pattern", "match_type", name="uq_transaction_type_rule_pattern_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False, default="EXACT")
    times_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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

    transactions: Mapped[list[Transaction]] = relationship("Transaction", back_populates="type_rule")


class CategoryRule(Base):
    __tablename__ = "category_rules"
    __table_args__ = (UniqueConstraint("pattern", "match_type", name="uq_category_rule_pattern_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    main_category: Mapped[str] = mapped_column(String(64), nullable=False)
    subcategory: Mapped[str] = mapped_column(String(64), nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False, default="EXACT")
    times_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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

    transactions: Mapped[list[Transaction]] = relationship("Transaction", back_populates="category_rule")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("statements.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    extraction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction_extractions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    transaction_date: Mapped[date] = mapped_column(Date(), nullable=False)
    transaction_detail: Mapped[str] = mapped_column(Text(), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    direction: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN")
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_confidence: Mapped[float] = mapped_column(Float(), nullable=False, default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    user_edited: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    user_added: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="EXTRACTED")
    original_transaction_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    original_transaction_detail: Mapped[str | None] = mapped_column(Text(), nullable=True)
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    original_direction: Mapped[str | None] = mapped_column(String(24), nullable=True)
    original_source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_source_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalization_confidence: Mapped[float] = mapped_column(Float(), nullable=False, default=0.0)
    normalization_source: Mapped[str] = mapped_column(String(32), nullable=False, default="UNRESOLVED")
    normalization_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_NORMALIZED")
    normalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_normalized_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_normalization_confidence: Mapped[float | None] = mapped_column(Float(), nullable=True)
    original_normalization_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    original_normalization_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_edited_normalization: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    normalization_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("merchant_normalization_rules.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    transaction_type: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    type_confidence: Mapped[float] = mapped_column(Float(), nullable=False, default=0.0)
    type_source: Mapped[str] = mapped_column(String(32), nullable=False, default="UNRESOLVED")
    type_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_CLASSIFIED")
    type_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suggested_include: Mapped[str] = mapped_column(String(16), nullable=False, default="REVIEW")
    original_transaction_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_type_confidence: Mapped[float | None] = mapped_column(Float(), nullable=True)
    original_type_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    original_type_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_suggested_include: Mapped[str | None] = mapped_column(String(16), nullable=True)
    user_edited_type: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    type_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction_type_rules.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    main_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category_confidence: Mapped[float] = mapped_column(Float(), nullable=False, default=0.0)
    category_source: Mapped[str] = mapped_column(String(32), nullable=False, default="UNRESOLVED")
    category_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_CATEGORIZED")
    category_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_main_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_subcategory: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_category_confidence: Mapped[float | None] = mapped_column(Float(), nullable=True)
    original_category_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    original_category_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_edited_category: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    category_rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("category_rules.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    include_in_expenses: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
    inclusion_initialized: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    inclusion_source: Mapped[str] = mapped_column(String(32), nullable=False, default="UNINITIALIZED")
    inclusion_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    review_source: Mapped[str] = mapped_column(String(32), nullable=False, default="SYSTEM")
    review_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    statement: Mapped[Statement] = relationship("Statement", back_populates="transactions")
    extraction: Mapped[TransactionExtraction | None] = relationship(
        "TransactionExtraction",
        back_populates="transactions",
    )
    normalization_rule: Mapped[MerchantNormalizationRule | None] = relationship(
        "MerchantNormalizationRule",
        back_populates="transactions",
    )
    type_rule: Mapped[TransactionTypeRule | None] = relationship(
        "TransactionTypeRule",
        back_populates="transactions",
    )
    category_rule: Mapped[CategoryRule | None] = relationship(
        "CategoryRule",
        back_populates="transactions",
    )


from app.models.statement import Statement  # noqa: E402
