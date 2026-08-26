from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.statement import StatementResponse
from app.schemas.transaction import TransactionExtractionResponse, TransactionResponse


AnalysisStepStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "SKIPPED"]
AnalysisStatus = Literal["COMPLETED", "FAILED"]


class AnalysisStepResponse(BaseModel):
    key: str
    label: str
    status: AnalysisStepStatus
    message: str | None = None


class RetentionRemovedFileResponse(BaseModel):
    file_id: int
    display_name: str
    institution: str
    removed_at: datetime | None
    reason: str


class RetentionSummaryResponse(BaseModel):
    institution: str | None = None
    removed_count: int = 0
    removed_files: list[RetentionRemovedFileResponse] = []


class StatementAnalysisResponse(BaseModel):
    status: AnalysisStatus
    failed_step: str | None = None
    statement: StatementResponse
    extraction: TransactionExtractionResponse | None = None
    transactions: list[TransactionResponse]
    steps: list[AnalysisStepResponse]
    retention: RetentionSummaryResponse
