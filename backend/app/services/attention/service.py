from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.file import StoredFile
from app.models.statement import Statement
from app.models.transaction import Transaction
from app.schemas.attention import AttentionCountResponse, AttentionItemResponse, AttentionListResponse
from app.services.attention.rules import (
    statement_attention_items,
    statement_transaction_review_attention_items,
    transaction_attention_items,
)
from app.services.attention.types import SEVERITY_ERROR, SEVERITY_REVIEW, AttentionItem


def list_attention_items(session: Session, *, limit: int = 100) -> AttentionListResponse:
    items = _collect_attention_items(session)
    items = _sort_attention_items(items)
    limited_items = items[:limit]
    return AttentionListResponse(
        total=len(items),
        blocking_total=sum(1 for item in items if item.blocking),
        review_total=sum(1 for item in items if item.severity == SEVERITY_REVIEW),
        ready_for_summary=not any(item.blocking for item in items),
        items=[_to_response(item) for item in limited_items],
    )


def count_attention_items(session: Session) -> AttentionCountResponse:
    items = _collect_attention_items(session)
    return AttentionCountResponse(
        total=len(items),
        blocking_total=sum(1 for item in items if item.blocking),
        review_total=sum(1 for item in items if item.severity == SEVERITY_REVIEW),
        ready_for_summary=not any(item.blocking for item in items),
    )


def _collect_attention_items(session: Session) -> list[AttentionItem]:
    statements = list(
        session.execute(
            select(Statement).options(
                selectinload(Statement.file).selectinload(StoredFile.folder),
                selectinload(Statement.transactions),
            )
        ).scalars().all()
    )
    transactions = list(
        session.execute(
            select(Transaction)
            .where(Transaction.excluded.is_(False))
            .options(
                selectinload(Transaction.statement)
                .selectinload(Statement.file)
                .selectinload(StoredFile.folder),
            )
        ).scalars().all()
    )

    items: list[AttentionItem] = []
    for statement in statements:
        items.extend(statement_attention_items(statement))
        items.extend(statement_transaction_review_attention_items(statement))
    for transaction in transactions:
        items.extend(transaction_attention_items(transaction))
    return items


def _sort_attention_items(items: list[AttentionItem]) -> list[AttentionItem]:
    severity_order = {SEVERITY_ERROR: 0, SEVERITY_REVIEW: 1}
    return sorted(
        items,
        key=lambda item: (
            severity_order.get(item.severity, 2),
            0 if item.blocking else 1,
            item.file_name or "",
            item.statement_id or 0,
            item.transaction_date.isoformat() if item.transaction_date else "",
            item.transaction_id or 0,
            item.attention_type,
        ),
    )


def _to_response(item: AttentionItem) -> AttentionItemResponse:
    return AttentionItemResponse(**asdict(item))
