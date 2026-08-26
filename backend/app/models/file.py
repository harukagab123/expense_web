from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class StoredFile(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file_available: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    source_file_removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_file_removal_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
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

    folder: Mapped[Folder | None] = relationship("Folder", back_populates="files")
    statement: Mapped[Statement | None] = relationship(
        "Statement",
        back_populates="file",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


from app.models.folder import Folder  # noqa: E402
from app.models.statement import Statement  # noqa: E402
