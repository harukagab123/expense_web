from __future__ import annotations

from app.services.transaction_extraction.base import PageText, ParseResult, ParserContext


class TjxTransactionParser:
    parser_name = "tjx"
    parser_version = "tjx-v1"

    def parse(self, pages: list[PageText], context: ParserContext) -> ParseResult:
        return ParseResult(
            transactions=[],
            message="This TJX PDF contains statement-level totals but no itemized transaction rows to extract.",
        )
