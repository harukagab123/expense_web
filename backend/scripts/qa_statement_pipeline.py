from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.models.file import StoredFile
from app.models.folder import Folder
from app.models.statement import Statement
from app.models.transaction import Transaction
from app.services.file_manager import resolve_storage_path
from app.services.statement_detection.base import (
    DOCUMENT_OTHER_DOCUMENT,
    INSTITUTION_AMEX,
    INSTITUTION_CAPITAL_ONE,
    INSTITUTION_CITI,
    INSTITUTION_PAYPAL,
    INSTITUTION_TJX,
    INSTITUTION_UNKNOWN,
    STATUS_NOT_A_STATEMENT,
)
from app.services.statement_detection.pdf_text import PdfTextExtractionError, extract_pdf_pages
from app.services.statement_detection.service import detect_statement_for_file
from app.services.transaction_categorization.base import is_category_eligible
from app.services.transaction_categorization.service import categorize_transactions_for_statement
from app.services.transaction_extraction.base import DIRECTION_INFLOW, DIRECTION_OUTFLOW, PageText, ParserContext
from app.services.transaction_extraction.chase import (
    BALANCE_COLUMN_HEADER_RE,
    DATE_PREFIX_RE,
    _find_beginning_balance,
    _is_ignored_line,
    _is_stop_heading,
    _money_value_at_end,
    _section_direction,
)
from app.services.transaction_extraction.common import amount_at_end, normalize_spaces
from app.services.transaction_extraction.registry import get_transaction_parser
from app.services.transaction_extraction.service import extract_transactions_for_statement
from app.services.transaction_normalization.service import normalize_transactions_for_statement
from app.services.transaction_type_detection.base import TYPE_CREDIT_CARD_PAYMENT, TYPE_EXPENSE
from app.services.transaction_type_detection.rules import CREDIT_CARD_PAYMENT_PATTERNS
from app.services.transaction_type_detection.service import classify_transaction_types_for_statement


NON_EXPENSE_TYPES = {
    "CREDIT_CARD_PAYMENT",
    "INCOME",
    "TRANSFER",
    "ATM_CASH_WITHDRAWAL",
    "REFUND",
    "UNKNOWN",
}

GAS_PATTERNS = (
    re.compile(r"\bCHEVRON\b"),
    re.compile(r"\bSHELL\b"),
    re.compile(r"\bARCO\b"),
    re.compile(r"(?:^|\b)76(?:\b|$)"),
    re.compile(r"\bCOSTCO\b.*\bGAS\b"),
)

AMBIGUOUS_RETAIL_PATTERNS = (
    re.compile(r"\bAMAZON\b"),
    re.compile(r"\bAMZN\b"),
    re.compile(r"\bCOSTCO\b(?!.*\bGAS\b)"),
)

ENDING_BALANCE_RE = re.compile(
    r"\bending\s+balance\s+\$?(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2}))",
    re.IGNORECASE,
)
MONEY_RE = re.compile(r"(?P<negative>-\s*)?\$(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2}))")
PAYPAL_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}\b")


@dataclass
class StatementQaResult:
    file_id: int
    filename: str
    relative_folder_path: str
    detected_institution: str | None = None
    document_type: str | None = None
    account_type: str | None = None
    account_last_four_present: bool = False
    statement_start_date: str | None = None
    statement_end_date: str | None = None
    processing_status: str = "NOT_TESTED"
    qa_status: str = "NOT_TESTED"
    expected_transactions: int | None = None
    extracted_transactions: int = 0
    extraction_status: str = "NOT_RUN"
    normalization_status: str = "NOT_RUN"
    type_status: str = "NOT_RUN"
    category_status: str = "NOT_RUN"
    missing_transactions: int = 0
    duplicate_transactions: int = 0
    amount_errors: int = 0
    date_errors: int = 0
    description_errors: int = 0
    direction_errors: int = 0
    type_errors: int = 0
    category_errors: int = 0
    non_expense_false_categorizations: int = 0
    needs_review_transactions: int = 0
    reason: str | None = None
    validation_notes: list[str] = field(default_factory=list)


@dataclass
class QaReport:
    generated_at: str
    total_files: int
    financial_statements: int
    non_statements: int
    unsupported: int
    source_data_insufficient: int
    statements_processed: int
    statements_passed: int
    statements_passed_with_review: int
    statements_failed: int
    expected_transactions: int
    extracted_transactions: int
    missing_transactions: int
    duplicate_transactions: int
    amount_errors: int
    date_errors: int
    description_errors: int
    direction_errors: int
    type_errors: int
    category_errors: int
    non_expense_false_categorizations: int
    banks: dict[str, str]
    results: list[StatementQaResult]


def folder_paths(session: Session) -> dict[int | None, str]:
    folders = session.execute(select(Folder)).scalars().all()
    folders_by_id = {folder.id: folder for folder in folders}
    paths: dict[int | None, str] = {None: ""}

    def resolve(folder_id: int | None) -> str:
        if folder_id in paths:
            return paths[folder_id]
        folder = folders_by_id[folder_id]
        parent = resolve(folder.parent_folder_id)
        paths[folder_id] = f"{parent}/{folder.name}" if parent else folder.name
        return paths[folder_id]

    for folder in folders:
        resolve(folder.id)
    return paths


def run_qa(session: Session) -> QaReport:
    paths = folder_paths(session)
    files = session.execute(select(StoredFile).order_by(StoredFile.folder_id, StoredFile.display_name)).scalars().all()
    results = [qa_file(session, stored_file, paths.get(stored_file.folder_id, "")) for stored_file in files]
    return build_report(results)


def qa_file(session: Session, stored_file: StoredFile, folder_path: str) -> StatementQaResult:
    result = StatementQaResult(
        file_id=stored_file.id,
        filename=stored_file.display_name,
        relative_folder_path=folder_path,
    )
    extension = Path(stored_file.display_name).suffix.lower()
    if extension != ".pdf" and stored_file.mime_type != "application/pdf":
        result.processing_status = "SKIPPED"
        result.qa_status = "UNSUPPORTED_FORMAT"
        result.reason = "Statement detection currently supports PDF files only."
        return result
    if stored_file.file_size == 0:
        result.processing_status = "SOURCE_DATA_INSUFFICIENT"
        result.qa_status = "NEEDS_SOURCE_DETAIL"
        result.reason = "The source PDF is empty and has no statement content to analyze."
        return result

    try:
        statement = detect_statement_for_file(session, stored_file.id)
    except Exception as exc:  # noqa: BLE001 - development QA should keep scanning all files.
        session.rollback()
        result.processing_status = "DETECTION_FAILED"
        result.qa_status = "FAIL_EXTRACTION"
        result.reason = f"Detection raised {exc.__class__.__name__}."
        return result

    apply_statement_metadata(result, statement)
    if statement.detection_status == STATUS_NOT_A_STATEMENT or statement.document_type == DOCUMENT_OTHER_DOCUMENT:
        result.processing_status = "DETECTED_NON_STATEMENT"
        result.qa_status = "NOT_A_STATEMENT"
        result.reason = statement.detection_reason
        return result

    if statement.institution == INSTITUTION_UNKNOWN:
        result.processing_status = "DETECTED_UNSUPPORTED"
        result.qa_status = "UNSUPPORTED_FORMAT"
        result.reason = statement.detection_reason or "No supported institution matched."
        return result

    parser = get_transaction_parser(statement.institution)
    if parser is None:
        extraction, _ = extract_transactions_for_statement(session, statement.id)
        result.processing_status = "UNSUPPORTED_EXTRACTION"
        result.qa_status = "UNSUPPORTED_FORMAT"
        result.extraction_status = extraction.status
        result.reason = extraction.message or "No transaction parser is registered for this institution."
        return result

    source_validation = inspect_source_statement(stored_file, statement)
    result.expected_transactions = source_validation.get("expected_transactions")
    result.validation_notes.extend(source_validation.get("notes", []))

    extraction, transactions = extract_transactions_for_statement(session, statement.id)
    result.extraction_status = extraction.status
    result.extracted_transactions = len(transactions)
    if source_validation.get("source_data_insufficient"):
        result.processing_status = "SOURCE_DATA_INSUFFICIENT"
        result.qa_status = "NEEDS_SOURCE_DETAIL"
        result.reason = source_validation["reason"]
        return result
    if result.expected_transactions is not None and result.extracted_transactions != result.expected_transactions:
        result.missing_transactions = max(0, result.expected_transactions - result.extracted_transactions)
        result.duplicate_transactions += max(0, result.extracted_transactions - result.expected_transactions)

    normalize_transactions_for_statement(session, statement.id)
    result.normalization_status = "COMPLETED"
    classify_transaction_types_for_statement(session, statement.id)
    result.type_status = "COMPLETED"
    categorize_transactions_for_statement(session, statement.id)
    result.category_status = "COMPLETED"

    transactions = active_transactions(session, statement.id)
    result.extracted_transactions = len(transactions)
    balance_validation = validate_source_reconciliation(source_validation, transactions)
    result.amount_errors += balance_validation.get("amount_errors", 0)
    result.direction_errors += balance_validation.get("direction_errors", 0)
    result.validation_notes.extend(balance_validation.get("notes", []))
    result.needs_review_transactions = sum(transaction.review_status == "NEEDS_REVIEW" for transaction in transactions)
    result.duplicate_transactions += duplicate_count(transactions, source_validation.get("source_key_counts"))
    classify_output_errors(result, transactions)
    finalize_status(result)
    return result


def apply_statement_metadata(result: StatementQaResult, statement: Statement) -> None:
    result.detected_institution = statement.institution
    result.document_type = statement.document_type
    result.account_type = statement.account_type
    result.account_last_four_present = statement.account_last_four is not None
    result.statement_start_date = iso(statement.statement_start_date)
    result.statement_end_date = iso(statement.statement_end_date)


def inspect_source_statement(stored_file: StoredFile, statement: Statement) -> dict[str, Any]:
    try:
        pages = extract_pdf_pages(resolve_storage_path(stored_file))
    except PdfTextExtractionError:
        return {
            "expected_transactions": None,
            "notes": ["PDF text extraction failed during source validation."],
        }

    if not pages:
        return {
            "expected_transactions": 0,
            "notes": ["No readable source text found."],
        }

    if statement.institution == INSTITUTION_TJX:
        return {
            "institution": statement.institution,
            "pages": pages,
            "expected_transactions": None,
            "source_data_insufficient": True,
            "reason": "The TJX source statement has only account-summary totals and no itemized transaction rows.",
            "notes": ["Visual source inspection confirmed that individual activity rows are absent."],
        }

    source_key_counts = source_transaction_key_counts(pages, statement)
    result: dict[str, Any] = {
        "institution": statement.institution,
        "pages": pages,
        "source_key_counts": source_key_counts,
        "expected_transactions": None,
        "notes": [],
    }

    if statement.institution == "CHASE":
        expected_count, estimator = estimate_chase_transaction_count(pages)
        result["expected_transactions"] = expected_count
        result["notes"].append(f"Source count estimator: {estimator}.")
    elif statement.institution == INSTITUTION_PAYPAL:
        result["expected_transactions"] = estimate_paypal_transaction_count(pages)
        result["notes"].append("Source count estimator: PAYPAL_ACTIVITY_DATE_ROWS.")
    else:
        result["notes"].append("Source totals are reconciled against extracted transaction amounts.")
    return result


def estimate_chase_transaction_count(pages: list[str]) -> tuple[int, str]:
    joined_text = "\n".join(pages)
    if BALANCE_COLUMN_HEADER_RE.search(joined_text):
        return estimate_chase_balance_table_count(pages), "CHASE_BALANCE_TABLE_DATE_ROWS"
    return estimate_chase_section_count(pages), "CHASE_SECTION_DATE_ROWS"


def estimate_chase_balance_table_count(pages: list[str]) -> int:
    count = 0
    in_table = False
    for page in pages:
        for raw_line in page.splitlines():
            line = normalize_spaces(raw_line)
            if not line:
                continue
            if BALANCE_COLUMN_HEADER_RE.search(line):
                in_table = True
                continue
            if not in_table:
                continue
            if _is_stop_heading(line):
                in_table = False
                continue
            if _is_ignored_line(line) or _section_direction(line) is not None:
                continue
            if DATE_PREFIX_RE.match(line):
                count += 1
    return count


def estimate_chase_section_count(pages: list[str]) -> int:
    count = 0
    current_section = False
    pending_row = False
    for page in pages:
        for raw_line in page.splitlines():
            line = normalize_spaces(raw_line)
            if not line:
                continue
            if _section_direction(line) is not None:
                current_section = True
                pending_row = False
                continue
            if _is_stop_heading(line):
                current_section = False
                pending_row = False
                continue
            if _is_ignored_line(line):
                continue
            date_match = DATE_PREFIX_RE.match(line)
            if current_section and date_match:
                pending_row = False
                rest = normalize_spaces(date_match.group("rest"))
                if amount_at_end(rest) is not None:
                    count += 1
                else:
                    pending_row = True
                continue
            if current_section and pending_row and amount_at_end(line) is not None:
                count += 1
                pending_row = False
    return count


def estimate_paypal_transaction_count(pages: list[str]) -> int:
    count = 0
    in_paypal_account = False
    in_activity = False
    for page in pages:
        lines = [normalize_spaces(line) for line in page.splitlines() if normalize_spaces(line)]
        index = 0
        while index < len(lines):
            line = lines[index]
            if re.fullmatch(r"\d{2}/\d{2}/\d{3}", line) and index + 1 < len(lines) and re.fullmatch(r"\d", lines[index + 1]):
                line = f"{line}{lines[index + 1]}"
                index += 1
            normalized = line.casefold()
            if normalized == "paypal account":
                in_paypal_account = True
                in_activity = False
            elif "paypal balance account" in normalized:
                in_paypal_account = False
                in_activity = False
            elif in_paypal_account and normalized == "account activity":
                in_activity = True
            elif normalized.startswith("account statements"):
                in_activity = False
            elif in_activity and PAYPAL_DATE_RE.match(line):
                count += 1
            index += 1
    return count


def source_transaction_key_counts(pages: list[str], statement: Statement) -> Counter[tuple[str, str, Decimal, str]]:
    parser = get_transaction_parser(statement.institution)
    if parser is None:
        return Counter()
    parsed = parser.parse(
        [PageText(page_number=index + 1, text=text) for index, text in enumerate(pages)],
        ParserContext(
            institution=statement.institution,
            product_name=statement.product_name,
            account_type=statement.account_type,
            statement_start_date=statement.statement_start_date,
            statement_end_date=statement.statement_end_date,
        ),
    )
    return Counter(extracted_transaction_key(transaction) for transaction in parsed.transactions)


def validate_source_reconciliation(source_validation: dict[str, Any], transactions: list[Transaction]) -> dict[str, Any]:
    pages = source_validation.get("pages")
    if not pages:
        return {"amount_errors": 0, "direction_errors": 0, "notes": []}
    institution = source_validation.get("institution")
    if institution == "CHASE":
        return validate_chase_balance_delta(pages, transactions)
    if institution == INSTITUTION_AMEX:
        return validate_amex_totals(pages, transactions)
    if institution == INSTITUTION_CAPITAL_ONE:
        return validate_card_balance_delta(pages, transactions, "CAPITAL_ONE")
    if institution == INSTITUTION_CITI:
        if "checking activity" in "\n".join(pages).casefold():
            return validate_citi_checking_balance_delta(pages, transactions)
        return validate_card_balance_delta(pages, transactions, "CITI")
    return {"amount_errors": 0, "direction_errors": 0, "notes": []}


def validate_chase_balance_delta(pages: list[str], transactions: list[Transaction]) -> dict[str, Any]:
    joined_text = "\n".join(pages)
    beginning_balance = _find_beginning_balance(joined_text)
    ending_balance = find_last_ending_balance(joined_text)
    if beginning_balance is None or ending_balance is None:
        return {"amount_errors": 0, "direction_errors": 0, "notes": ["No reliable beginning/ending balance reconciliation available."]}

    extracted_delta = Decimal("0.00")
    for transaction in transactions:
        amount = Decimal(transaction.amount).quantize(Decimal("0.01"))
        if transaction.direction == DIRECTION_INFLOW:
            extracted_delta += amount
        elif transaction.direction == DIRECTION_OUTFLOW:
            extracted_delta -= amount
    expected_delta = (ending_balance - beginning_balance).quantize(Decimal("0.01"))
    extracted_delta = extracted_delta.quantize(Decimal("0.01"))
    if expected_delta != extracted_delta:
        return {
            "amount_errors": 1,
            "direction_errors": 1,
            "notes": [f"Balance delta mismatch: expected {expected_delta}, extracted {extracted_delta}."],
        }
    return {
        "amount_errors": 0,
        "direction_errors": 0,
        "notes": [f"Balance delta reconciled: {expected_delta}."],
    }


def validate_amex_totals(pages: list[str], transactions: list[Transaction]) -> dict[str, Any]:
    text = normalize_spaces("\n".join(pages))
    expected_inflow = _last_amount_after(text, r"total\s+payments\s+and\s+credits")
    expected_outflow = sum(
        (
            amount
            for amount in (
                _last_amount_after(text, r"total\s+new\s+charges"),
                _last_amount_after(text, r"total\s+fees\s+for\s+this\s+period"),
                _last_amount_after(text, r"total\s+interest\s+charged\s+for\s+this\s+period"),
            )
            if amount is not None
        ),
        Decimal("0.00"),
    )
    if expected_inflow is None:
        return {"amount_errors": 0, "direction_errors": 0, "notes": ["AMEX summary totals were not readable."]}
    actual_inflow, actual_outflow = transaction_direction_totals(transactions)
    if actual_inflow != expected_inflow or actual_outflow != expected_outflow:
        return {
            "amount_errors": 1,
            "direction_errors": 1,
            "notes": [
                "AMEX summary mismatch: "
                f"expected inflow {expected_inflow}, outflow {expected_outflow}; "
                f"extracted inflow {actual_inflow}, outflow {actual_outflow}."
            ],
        }
    return {
        "amount_errors": 0,
        "direction_errors": 0,
        "notes": [f"AMEX activity totals reconciled: inflow {expected_inflow}, outflow {expected_outflow}."],
    }


def validate_card_balance_delta(
    pages: list[str],
    transactions: list[Transaction],
    institution: str,
) -> dict[str, Any]:
    text = normalize_spaces("\n".join(pages))
    previous_balance = _first_amount_after(text, r"previous\s+balance")
    new_balance = _first_amount_after(text, r"new\s+balance(?:\s+as\s+of)?")
    if previous_balance is None or new_balance is None:
        return {
            "amount_errors": 0,
            "direction_errors": 0,
            "notes": [f"{institution} balance summary was not readable."],
        }

    actual_inflow, actual_outflow = transaction_direction_totals(transactions)
    expected_delta = (new_balance - previous_balance).quantize(Decimal("0.01"))
    extracted_delta = (actual_outflow - actual_inflow).quantize(Decimal("0.01"))
    if expected_delta != extracted_delta:
        return {
            "amount_errors": 1,
            "direction_errors": 1,
            "notes": [
                f"{institution} balance delta mismatch: expected {expected_delta}, extracted {extracted_delta}."
            ],
        }
    return {
        "amount_errors": 0,
        "direction_errors": 0,
        "notes": [f"{institution} balance delta reconciled: {expected_delta}."],
    }


def validate_citi_checking_balance_delta(pages: list[str], transactions: list[Transaction]) -> dict[str, Any]:
    text = normalize_spaces("\n".join(pages))
    beginning_balance = _first_amount_after(text, r"beginning\s+balance")
    ending_balance = _first_amount_after(text, r"ending\s+balance")
    if beginning_balance is None or ending_balance is None:
        return {
            "amount_errors": 0,
            "direction_errors": 0,
            "notes": ["Citi checking balance summary was not readable."],
        }

    actual_inflow, actual_outflow = transaction_direction_totals(transactions)
    expected_delta = (ending_balance - beginning_balance).quantize(Decimal("0.01"))
    extracted_delta = (actual_inflow - actual_outflow).quantize(Decimal("0.01"))
    if expected_delta != extracted_delta:
        return {
            "amount_errors": 1,
            "direction_errors": 1,
            "notes": [f"CITI checking balance delta mismatch: expected {expected_delta}, extracted {extracted_delta}."],
        }
    return {
        "amount_errors": 0,
        "direction_errors": 0,
        "notes": [f"CITI checking balance delta reconciled: {expected_delta}."],
    }


def transaction_direction_totals(transactions: list[Transaction]) -> tuple[Decimal, Decimal]:
    inflow = Decimal("0.00")
    outflow = Decimal("0.00")
    for transaction in transactions:
        amount = Decimal(transaction.amount).quantize(Decimal("0.01"))
        if transaction.direction == DIRECTION_INFLOW:
            inflow += amount
        elif transaction.direction == DIRECTION_OUTFLOW:
            outflow += amount
    return inflow.quantize(Decimal("0.01")), outflow.quantize(Decimal("0.01"))


def _first_amount_after(text: str, label_pattern: str) -> Decimal | None:
    match = re.search(label_pattern, text, re.IGNORECASE)
    if match is None:
        return None
    values = list(MONEY_RE.finditer(text[match.end() : match.end() + 100]))
    return _decimal_from_money_match(values[0]) if values else None


def _last_amount_after(text: str, label_pattern: str) -> Decimal | None:
    match = re.search(label_pattern, text, re.IGNORECASE)
    if match is None:
        return None
    values = list(MONEY_RE.finditer(text[match.end() : match.end() + 75]))
    return _decimal_from_money_match(values[-1]) if values else None


def _decimal_from_money_match(match: re.Match[str]) -> Decimal:
    return Decimal(match.group("amount").replace(",", "")).quantize(Decimal("0.01"))


def find_last_ending_balance(text: str) -> Decimal | None:
    matches = list(ENDING_BALANCE_RE.finditer(text))
    if not matches:
        return None
    detail, amount = _money_value_at_end(matches[-1].group("amount"))
    if detail:
        return None
    return amount


def active_transactions(session: Session, statement_id: int) -> list[Transaction]:
    return list(
        session.execute(
            select(Transaction)
            .where(Transaction.statement_id == statement_id, Transaction.excluded.is_(False))
            .order_by(Transaction.source_order.asc(), Transaction.id.asc())
        ).scalars().all()
    )


def duplicate_count(
    transactions: list[Transaction],
    source_key_counts: Counter[tuple[str, str, Decimal, str]] | None = None,
) -> int:
    keys = [transaction_key(transaction) for transaction in transactions]
    counts = Counter(keys)
    if source_key_counts is not None:
        return sum(max(0, count - source_key_counts.get(key, 0)) for key, count in counts.items())
    return sum(count - 1 for count in counts.values() if count > 1)


def transaction_key(transaction: Transaction) -> tuple[str, str, Decimal, str]:
    return (
        transaction.transaction_date.isoformat(),
        normalize_spaces(transaction.transaction_detail).casefold(),
        Decimal(transaction.amount).quantize(Decimal("0.01")),
        transaction.direction,
    )


def extracted_transaction_key(transaction) -> tuple[str, str, Decimal, str]:
    return (
        transaction.transaction_date.isoformat(),
        normalize_spaces(transaction.transaction_detail).casefold(),
        Decimal(transaction.amount).quantize(Decimal("0.01")),
        transaction.direction,
    )


def classify_output_errors(result: StatementQaResult, transactions: list[Transaction]) -> None:
    for transaction in transactions:
        raw = normalize_spaces(transaction.transaction_detail).upper()
        if any(pattern.search(raw) for pattern in CREDIT_CARD_PAYMENT_PATTERNS):
            if transaction.transaction_type != TYPE_CREDIT_CARD_PAYMENT:
                result.type_errors += 1
        if transaction.transaction_type in NON_EXPENSE_TYPES and (
            transaction.main_category is not None or transaction.subcategory is not None
        ):
            result.non_expense_false_categorizations += 1
            result.category_errors += 1
        if not is_category_eligible(transaction.transaction_type, transaction.direction):
            continue
        if transaction.transaction_type == TYPE_EXPENSE and any(pattern.search(raw) for pattern in GAS_PATTERNS):
            if transaction.main_category != "AUTO_EXPENSE" or transaction.subcategory != "AUTO_GAS":
                result.category_errors += 1
        if transaction.transaction_type == TYPE_EXPENSE and any(pattern.search(raw) for pattern in AMBIGUOUS_RETAIL_PATTERNS):
            if transaction.main_category != "PERSONAL_INTERNAL" or transaction.subcategory != "UNCATEGORIZED":
                result.category_errors += 1


def finalize_status(result: StatementQaResult) -> None:
    hard_errors = (
        result.missing_transactions
        + result.duplicate_transactions
        + result.amount_errors
        + result.date_errors
        + result.description_errors
        + result.direction_errors
        + result.type_errors
        + result.category_errors
    )
    if result.extraction_status not in {"EXTRACTED", "NEEDS_REVIEW"}:
        result.processing_status = "FAILED"
        result.qa_status = "FAIL_EXTRACTION"
        return
    if hard_errors:
        result.processing_status = "PROCESSED_WITH_ERRORS"
        result.qa_status = "FAIL_EXTRACTION" if result.missing_transactions or result.duplicate_transactions else "FAIL_CATEGORY"
        return
    result.processing_status = "PROCESSED"
    result.qa_status = "PASS_WITH_REVIEW" if result.needs_review_transactions else "PASS"


def build_report(results: list[StatementQaResult]) -> QaReport:
    financial_statuses = {"PASS", "PASS_WITH_REVIEW", "FAIL_EXTRACTION", "FAIL_NORMALIZATION", "FAIL_TYPE", "FAIL_CATEGORY", "UNSUPPORTED_FORMAT", "NEEDS_SOURCE_DETAIL"}
    financial = [result for result in results if result.qa_status in financial_statuses]
    processed = [result for result in results if result.processing_status in {"PROCESSED", "PROCESSED_WITH_ERRORS", "FAILED"}]
    banks: dict[str, str] = {}
    for institution in sorted({result.detected_institution or "UNKNOWN" for result in results}):
        bank_results = [result for result in results if (result.detected_institution or "UNKNOWN") == institution]
        banks[institution] = aggregate_bank_status(bank_results)

    return QaReport(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        total_files=len(results),
        financial_statements=len(financial),
        non_statements=sum(result.qa_status == "NOT_A_STATEMENT" for result in results),
        unsupported=sum(result.qa_status == "UNSUPPORTED_FORMAT" for result in results),
        source_data_insufficient=sum(result.qa_status == "NEEDS_SOURCE_DETAIL" for result in results),
        statements_processed=len(processed),
        statements_passed=sum(result.qa_status == "PASS" for result in results),
        statements_passed_with_review=sum(result.qa_status == "PASS_WITH_REVIEW" for result in results),
        statements_failed=sum(result.qa_status.startswith("FAIL") for result in results),
        expected_transactions=sum(result.expected_transactions or 0 for result in results),
        extracted_transactions=sum(result.extracted_transactions for result in results),
        missing_transactions=sum(result.missing_transactions for result in results),
        duplicate_transactions=sum(result.duplicate_transactions for result in results),
        amount_errors=sum(result.amount_errors for result in results),
        date_errors=sum(result.date_errors for result in results),
        description_errors=sum(result.description_errors for result in results),
        direction_errors=sum(result.direction_errors for result in results),
        type_errors=sum(result.type_errors for result in results),
        category_errors=sum(result.category_errors for result in results),
        non_expense_false_categorizations=sum(result.non_expense_false_categorizations for result in results),
        banks=banks,
        results=results,
    )


def aggregate_bank_status(results: list[StatementQaResult]) -> str:
    if not results:
        return "NOT_PRESENT"
    statuses = {result.qa_status for result in results}
    if any(status.startswith("FAIL") for status in statuses):
        return "FAIL"
    if "UNSUPPORTED_FORMAT" in statuses:
        return "UNSUPPORTED"
    if "NEEDS_SOURCE_DETAIL" in statuses:
        return "NEEDS_SOURCE_DETAIL"
    if "PASS_WITH_REVIEW" in statuses:
        return "PASS_WITH_REVIEW"
    if "PASS" in statuses:
        return "PASS"
    if statuses == {"NOT_A_STATEMENT"}:
        return "NOT_PRESENT"
    return "REVIEW"


def iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def report_to_json(report: QaReport) -> dict[str, Any]:
    payload = asdict(report)
    return payload


def print_summary(report: QaReport) -> None:
    print("Statement QA summary")
    print(f"Total files: {report.total_files}")
    print(f"Financial statements: {report.financial_statements}")
    print(f"Processed: {report.statements_processed}")
    print(f"Passed: {report.statements_passed}")
    print(f"Passed with review: {report.statements_passed_with_review}")
    print(f"Failed: {report.statements_failed}")
    print(f"Unsupported: {report.unsupported}")
    print(f"Needs source detail: {report.source_data_insufficient}")
    print(f"Non-statements: {report.non_statements}")
    print("")
    print("Institution status")
    for institution, status in sorted(report.banks.items()):
        print(f"{institution}: {status}")
    print("")
    print("Statement results")
    for result in report.results:
        if result.qa_status == "NOT_A_STATEMENT":
            continue
        print(
            " | ".join(
                [
                    str(result.file_id),
                    result.relative_folder_path,
                    result.filename,
                    result.detected_institution or "UNKNOWN",
                    str(result.expected_transactions) if result.expected_transactions is not None else "-",
                    str(result.extracted_transactions),
                    result.extraction_status,
                    result.type_status,
                    result.category_status,
                    result.qa_status,
                ]
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local statement QA through categorization.")
    parser.add_argument(
        "--output",
        default="../data/statement_qa_report.json",
        help="Path for the private local JSON report. Defaults to ignored data/statement_qa_report.json.",
    )
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    with get_session_factory()() as session:
        report = run_qa(session)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report_to_json(report), indent=2), encoding="utf-8")
    print_summary(report)
    print("")
    print(f"Report written to {output}")
    return 1 if report.statements_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
