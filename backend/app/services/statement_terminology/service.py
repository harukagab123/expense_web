from __future__ import annotations

from datetime import UTC, datetime
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transaction import StatementTerm, Transaction
from app.services.statement_terminology.engine import TermDefinition, interpret_description, normalize_institution
from app.services.transaction_extraction.service import get_statement_or_404


TERM_CATEGORY_CONFIRMATIONS = {
    ("PARKING", "AUTO_EXPENSE", "AUTO_PARKING"),
}

BUILT_IN_TERMS = (
    ("PRK", "Parking", "GLOBAL", "GARAGE|METER|CITY", 0.80),
    ("PRK", "Parking", "CHASE", "GARAGE|METER|CITY", 0.87),
    ("PMT", "Payment", "GLOBAL", "ANY", 0.86),
    ("PYMT", "Payment", "GLOBAL", "ANY", 0.86),
    ("PAYMNT", "Payment", "GLOBAL", "ANY", 0.88),
    ("AUTO PMT", "Automatic Payment", "GLOBAL", "ANY", 0.96),
    ("AUTOPAY", "Automatic Payment", "GLOBAL", "ANY", 0.96),
    ("ACH PMT", "ACH Payment", "GLOBAL", "ANY", 0.97),
    ("ACH", "Automated Clearing House", "GLOBAL", "ANY", 0.90),
    ("POS", "Point of Sale", "GLOBAL", "ANY", 0.86),
    ("DBT", "Debit", "GLOBAL", "ANY", 0.84),
    ("CRD", "Card", "GLOBAL", "ANY", 0.84),
    ("AMZN", "Amazon", "GLOBAL", "ANY", 0.97),
    ("MKTPL", "Marketplace", "GLOBAL", "ANY", 0.96),
    ("WHSE", "Warehouse", "GLOBAL", "ANY", 0.94),
    ("AMEX", "American Express", "GLOBAL", "ANY", 0.97),
)


def interpret_transactions_for_statement(session: Session, statement_id: int) -> list[Transaction]:
    statement = get_statement_or_404(session, statement_id)
    _ensure_builtin_terms(session)
    terms = _load_terms(session, statement.institution)
    definitions = [_to_definition(term) for term in terms]
    terms_by_id = {term.id: term for term in terms}
    transactions = _list_active_transactions(session, statement_id)
    now = datetime.now(UTC)

    for transaction in transactions:
        result = interpret_description(transaction.transaction_detail, statement.institution, definitions)
        transaction.interpreted_detail = result.interpreted_detail
        transaction.terminology_confidence = result.confidence
        transaction.terminology_matches = json.dumps(
            [
                {
                    "term_id": match.term_id,
                    "term": match.term,
                    "meaning": match.meaning,
                    "institution": match.institution,
                    "confidence": round(match.confidence, 4),
                }
                for match in result.matches
            ]
        )
        transaction.terminology_updated_at = now
        for term_id in {match.term_id for match in result.matches}:
            terms_by_id[term_id].times_seen += 1

    session.commit()
    return _list_active_transactions(session, statement_id)


def list_statement_terms(session: Session) -> list[StatementTerm]:
    _ensure_builtin_terms(session)
    session.commit()
    return list(
        session.execute(
            select(StatementTerm).order_by(
                StatementTerm.term.asc(),
                StatementTerm.institution.asc(),
                StatementTerm.context.asc(),
            )
        ).scalars().all()
    )


def confirm_statement_term(session: Session, term_id: int) -> StatementTerm:
    term = session.get(StatementTerm, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="Statement terminology not found.")
    term.times_confirmed += 1
    term.source = "USER_CONFIRMED"
    session.commit()
    session.refresh(term)
    return term


def confirm_terms_from_category(
    session: Session,
    transaction: Transaction,
    main_category: str,
    subcategory: str,
) -> None:
    try:
        matches = json.loads(transaction.terminology_matches or "[]")
    except (TypeError, ValueError):
        return
    confirmed_ids = {
        int(match["term_id"])
        for match in matches
        if isinstance(match, dict)
        and "term_id" in match
        and (str(match.get("meaning", "")).upper(), main_category, subcategory) in TERM_CATEGORY_CONFIRMATIONS
    }
    if not confirmed_ids:
        return
    terms = session.execute(select(StatementTerm).where(StatementTerm.id.in_(confirmed_ids))).scalars().all()
    for term in terms:
        term.times_confirmed += 1


def _load_terms(session: Session, institution: str) -> list[StatementTerm]:
    institution_key = normalize_institution(institution)
    return list(
        session.execute(
            select(StatementTerm).where(StatementTerm.institution.in_(["GLOBAL", institution_key]))
        ).scalars().all()
    )


def _ensure_builtin_terms(session: Session) -> None:
    existing = {
        (term, institution, context)
        for term, institution, context in session.execute(
            select(StatementTerm.term, StatementTerm.institution, StatementTerm.context)
        ).all()
    }
    for term, meaning, institution, context, confidence in BUILT_IN_TERMS:
        if (term, institution, context) in existing:
            continue
        session.add(
            StatementTerm(
                term=term,
                normalized_meaning=meaning,
                institution=institution,
                context=context,
                confidence=confidence,
                source="BUILT_IN",
            )
        )
    session.flush()


def _to_definition(term: StatementTerm) -> TermDefinition:
    return TermDefinition(
        id=term.id,
        term=term.term,
        normalized_meaning=term.normalized_meaning,
        institution=term.institution,
        context=term.context,
        confidence=term.confidence,
        times_confirmed=term.times_confirmed,
    )


def _list_active_transactions(session: Session, statement_id: int) -> list[Transaction]:
    return list(
        session.execute(
            select(Transaction)
            .where(Transaction.statement_id == statement_id, Transaction.excluded.is_(False))
            .order_by(Transaction.source_order.asc(), Transaction.id.asc())
        ).scalars().all()
    )
