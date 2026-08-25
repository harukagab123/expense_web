from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


DIRECTION_INFLOW = "INFLOW"
DIRECTION_OUTFLOW = "OUTFLOW"
DIRECTION_UNKNOWN = "UNKNOWN"

SOURCE_EXTRACTED = "EXTRACTED"
SOURCE_USER_ADDED = "USER_ADDED"

STATUS_NOT_EXTRACTED = "NOT_EXTRACTED"
STATUS_EXTRACTING = "EXTRACTING"
STATUS_EXTRACTED = "EXTRACTED"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_FAILED = "FAILED"
STATUS_UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True)
class ParserContext:
    institution: str
    product_name: str | None
    account_type: str
    statement_start_date: date | None
    statement_end_date: date | None


@dataclass(frozen=True)
class ExtractedTransaction:
    transaction_date: date
    transaction_detail: str
    amount: Decimal
    direction: str
    source_page: int | None
    source_order: int
    extraction_confidence: float
    needs_review: bool


@dataclass(frozen=True)
class ParseResult:
    transactions: list[ExtractedTransaction]
    message: str | None = None


class TransactionParser(Protocol):
    parser_name: str
    parser_version: str

    def parse(self, pages: list[PageText], context: ParserContext) -> ParseResult:
        ...
