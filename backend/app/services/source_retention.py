from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.file import StoredFile
from app.models.statement import Statement
from app.services.file_manager import SOURCE_FILE_REMOVAL_RETENTION, mark_source_file_removed_by_retention
from app.services.statement_detection.base import (
    DOCUMENT_BANK_STATEMENT,
    DOCUMENT_CREDIT_CARD_STATEMENT,
    DOCUMENT_PAYMENT_ACCOUNT_STATEMENT,
    INSTITUTION_UNKNOWN,
)

logger = logging.getLogger(__name__)

MAX_STORED_SOURCE_FILES_PER_INSTITUTION = 5
FINANCIAL_STATEMENT_DOCUMENT_TYPES = {
    DOCUMENT_BANK_STATEMENT,
    DOCUMENT_CREDIT_CARD_STATEMENT,
    DOCUMENT_PAYMENT_ACCOUNT_STATEMENT,
}


@dataclass(frozen=True)
class RetentionRemovedFile:
    file_id: int
    display_name: str
    institution: str
    removed_at: datetime | None
    reason: str


@dataclass(frozen=True)
class RetentionResult:
    institution: str | None = None
    removed_files: list[RetentionRemovedFile] = field(default_factory=list)

    @property
    def removed_count(self) -> int:
        return len(self.removed_files)


def apply_retention_for_statement(session: Session, statement: Statement) -> RetentionResult:
    if not _is_retention_eligible(statement):
        return RetentionResult(institution=statement.institution)
    return apply_retention_for_institution(session, statement.institution)


def apply_retention_for_institution(session: Session, institution: str) -> RetentionResult:
    if institution == INSTITUTION_UNKNOWN:
        return RetentionResult(institution=institution)

    statements = list(
        session.execute(
            select(Statement)
            .join(Statement.file)
            .options(selectinload(Statement.file))
            .where(
                Statement.institution == institution,
                Statement.document_type.in_(FINANCIAL_STATEMENT_DOCUMENT_TYPES),
                StoredFile.source_file_available.is_(True),
            )
        ).scalars().all()
    )
    if len(statements) <= MAX_STORED_SOURCE_FILES_PER_INSTITUTION:
        return RetentionResult(institution=institution)

    ordered = sorted(statements, key=_statement_recency_key, reverse=True)
    remove_candidates = ordered[MAX_STORED_SOURCE_FILES_PER_INSTITUTION:]
    removed: list[RetentionRemovedFile] = []

    for statement in remove_candidates:
        stored_file = statement.file
        mark_source_file_removed_by_retention(session, stored_file)
        removed.append(
            RetentionRemovedFile(
                file_id=stored_file.id,
                display_name=stored_file.display_name,
                institution=institution,
                removed_at=stored_file.source_file_removed_at,
                reason=stored_file.source_file_removal_reason or SOURCE_FILE_REMOVAL_RETENTION,
            )
        )
        logger.info(
            "Retention removed old source statement file. institution=%s file_id=%s",
            institution,
            stored_file.id,
        )

    session.commit()
    return RetentionResult(institution=institution, removed_files=removed)


def _is_retention_eligible(statement: Statement) -> bool:
    return (
        statement.institution != INSTITUTION_UNKNOWN
        and statement.document_type in FINANCIAL_STATEMENT_DOCUMENT_TYPES
        and statement.file.source_file_available
    )


def _statement_recency_key(statement: Statement) -> tuple[date, datetime, int]:
    recency_date = statement.statement_end_date or statement.statement_start_date or statement.file.created_at.date()
    return (recency_date, statement.file.created_at, statement.file.id)
