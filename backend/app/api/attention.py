from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.attention import AttentionCountResponse, AttentionListResponse
from app.services.attention import count_attention_items, list_attention_items

router = APIRouter(prefix="/attention", tags=["attention"])


@router.get("/count", response_model=AttentionCountResponse)
def read_attention_count(db: Session = Depends(get_db)) -> AttentionCountResponse:
    return count_attention_items(db)


@router.get("", response_model=AttentionListResponse)
def read_attention_items(limit: int = 100, db: Session = Depends(get_db)) -> AttentionListResponse:
    return list_attention_items(db, limit=limit)
