from __future__ import annotations

from app.services.statement_detection.base import (
    INSTITUTION_AMEX,
    INSTITUTION_CAPITAL_ONE,
    INSTITUTION_CHASE,
    INSTITUTION_CITI,
    INSTITUTION_PAYPAL,
    INSTITUTION_TJX,
)
from app.services.transaction_extraction.base import TransactionParser
from app.services.transaction_extraction.amex import AmexTransactionParser
from app.services.transaction_extraction.chase import ChaseTransactionParser
from app.services.transaction_extraction.capital_one import CapitalOneTransactionParser
from app.services.transaction_extraction.citi import CitiTransactionParser
from app.services.transaction_extraction.paypal import PayPalTransactionParser
from app.services.transaction_extraction.tjx import TjxTransactionParser


PARSERS: dict[str, TransactionParser] = {
    INSTITUTION_CHASE: ChaseTransactionParser(),
    INSTITUTION_AMEX: AmexTransactionParser(),
    INSTITUTION_CAPITAL_ONE: CapitalOneTransactionParser(),
    INSTITUTION_CITI: CitiTransactionParser(),
    INSTITUTION_PAYPAL: PayPalTransactionParser(),
    INSTITUTION_TJX: TjxTransactionParser(),
}


def get_transaction_parser(institution: str) -> TransactionParser | None:
    return PARSERS.get(institution)
