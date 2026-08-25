from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
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

    parent: Mapped[Folder | None] = relationship(
        "Folder",
        remote_side=[id],
        back_populates="children",
    )
    children: Mapped[list[Folder]] = relationship(
        "Folder",
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    files: Mapped[list[StoredFile]] = relationship(
        "StoredFile",
        back_populates="folder",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


from app.models.file import StoredFile  # noqa: E402
