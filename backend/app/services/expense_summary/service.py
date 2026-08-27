from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import extract, select
from sqlalchemy.orm import Session, joinedload

from app.models.statement import Statement
from app.models.transaction import Transaction
from app.schemas.summary import (
    ExpenseSummaryResponse,
    SummaryGroupResponse,
    SummaryMetricsResponse,
    SummaryPeriodResponse,
    SummarySubcategoryResponse,
    SummaryTransactionResponse,
)
from app.services.transaction_categorization.base import (
    BUSINESS_OTHER_SUPPLIES,
    CATEGORY_CATALOG,
    CATEGORY_PRIORITY_INDEX,
    STATUS_NEEDS_REVIEW,
    STATUS_NOT_APPLICABLE,
    is_category_eligible,
    is_valid_category_pair,
)

CENT = Decimal("0.01")
MIN_YEAR = 1900
MAX_YEAR = 2200

MAIN_LABELS = {category.id: category.label for category in CATEGORY_CATALOG}
SUBCATEGORY_LABELS = {
    subcategory.id: subcategory.label
    for category in CATEGORY_CATALOG
    for subcategory in category.subcategories
}


@dataclass(frozen=True)
class ReportingPeriod:
    mode: str
    label: str
    start_date: date
    end_date: date
    tax_year: int | None
    available_years: list[int]


@dataclass(frozen=True)
class SummaryReconciliation:
    expected_transaction_ids: tuple[int, ...]
    summary_transaction_ids: tuple[int, ...]
    missing_transaction_ids: tuple[int, ...]
    unexpected_transaction_ids: tuple[int, ...]
    expected_total: Decimal
    summary_total: Decimal
    difference: Decimal


def available_transaction_years(session: Session) -> list[int]:
    rows = session.execute(
        select(extract("year", Transaction.transaction_date).label("year"))
        .where(Transaction.excluded.is_(False))
        .distinct()
        .order_by(extract("year", Transaction.transaction_date).desc())
    ).all()
    return [int(row.year) for row in rows if row.year is not None]


def resolve_reporting_period(
    session: Session,
    *,
    tax_year: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> ReportingPeriod:
    years = available_transaction_years(session)
    custom_requested = start_date is not None or end_date is not None
    if custom_requested:
        if start_date is None or end_date is None:
            raise HTTPException(status_code=422, detail="Start date and end date are both required.")
        if start_date > end_date:
            raise HTTPException(status_code=422, detail="Start date must be on or before end date.")
        return ReportingPeriod(
            mode="CUSTOM",
            label=f"{start_date.isoformat()} to {end_date.isoformat()}",
            start_date=start_date,
            end_date=end_date,
            tax_year=None,
            available_years=years,
        )

    selected_year = tax_year if tax_year is not None else (years[0] if years else date.today().year)
    if selected_year < MIN_YEAR or selected_year > MAX_YEAR:
        raise HTTPException(status_code=422, detail="Tax year is outside the supported range.")
    return ReportingPeriod(
        mode="TAX_YEAR",
        label=str(selected_year),
        start_date=date(selected_year, 1, 1),
        end_date=date(selected_year, 12, 31),
        tax_year=selected_year,
        available_years=years,
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _money_text(value: Decimal) -> str:
    return f"{_money(value):.2f}"


def normalized_expense_amount(transaction: Transaction) -> Decimal:
    amount = _money(Decimal(transaction.amount).copy_abs())
    return -amount if transaction.direction == "INFLOW" else amount


def _transaction_response(transaction: Transaction, amount: Decimal) -> SummaryTransactionResponse:
    statement = transaction.statement
    stored_file = statement.file
    return SummaryTransactionResponse(
        id=transaction.id,
        statement_id=statement.id,
        file_id=stored_file.id,
        transaction_date=transaction.transaction_date,
        normalized_name=transaction.normalized_name,
        transaction_detail=transaction.transaction_detail,
        institution=statement.institution,
        source_file=stored_file.display_name,
        source_file_available=stored_file.source_file_available,
        transaction_type=transaction.transaction_type,
        direction=transaction.direction,
        main_category=transaction.main_category,
        main_category_label=MAIN_LABELS.get(transaction.main_category or ""),
        subcategory=transaction.subcategory,
        subcategory_label=SUBCATEGORY_LABELS.get(transaction.subcategory or ""),
        amount=_money_text(amount),
        category_status=transaction.category_status,
        review_status=transaction.review_status,
    )


def is_expense_reporting_eligible(transaction: Transaction) -> bool:
    if transaction.excluded:
        return False
    if is_category_eligible(transaction.transaction_type, transaction.direction):
        return True

    # A manual category correction is user-authoritative evidence that an
    # unresolved outflow is an expense. Known non-expense types still follow
    # their existing exclusion rules and cannot enter the report this way.
    return bool(
        transaction.transaction_type == "UNKNOWN"
        and transaction.direction == "OUTFLOW"
        and transaction.user_edited_category
        and transaction.category_status == "USER_CONFIRMED"
        and transaction.main_category
        and transaction.subcategory
        and is_valid_category_pair(transaction.main_category, transaction.subcategory)
    )


def _has_valid_report_category(transaction: Transaction) -> bool:
    return bool(
        transaction.main_category
        and transaction.subcategory
        and is_valid_category_pair(transaction.main_category, transaction.subcategory)
        and transaction.category_status != STATUS_NOT_APPLICABLE
    )


def contributing_summary_transactions(transactions: Iterable[Transaction]) -> list[Transaction]:
    return [
        transaction
        for transaction in transactions
        if transaction.include_in_expenses is True
        and is_expense_reporting_eligible(transaction)
        and _has_valid_report_category(transaction)
    ]


def summary_transaction_ids(summary: ExpenseSummaryResponse) -> tuple[int, ...]:
    return tuple(
        transaction.id
        for group in summary.groups
        for subcategory in group.subcategories
        for transaction in subcategory.transactions
    )


def reconcile_expense_summary(
    expected_transactions: Iterable[Transaction],
    summary: ExpenseSummaryResponse,
) -> SummaryReconciliation:
    expected = list(expected_transactions)
    expected_ids = tuple(sorted(transaction.id for transaction in expected))
    actual_ids = tuple(sorted(summary_transaction_ids(summary)))
    expected_id_set = set(expected_ids)
    actual_id_set = set(actual_ids)
    expected_total = _money(
        sum((normalized_expense_amount(transaction) for transaction in expected), Decimal("0.00"))
    )
    actual_total = _money(Decimal(summary.grand_total))
    return SummaryReconciliation(
        expected_transaction_ids=expected_ids,
        summary_transaction_ids=actual_ids,
        missing_transaction_ids=tuple(sorted(expected_id_set - actual_id_set)),
        unexpected_transaction_ids=tuple(sorted(actual_id_set - expected_id_set)),
        expected_total=expected_total,
        summary_total=actual_total,
        difference=_money(actual_total - expected_total),
    )


def build_expense_summary(
    session: Session,
    *,
    tax_year: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> ExpenseSummaryResponse:
    period = resolve_reporting_period(
        session,
        tax_year=tax_year,
        start_date=start_date,
        end_date=end_date,
    )
    transactions = list(
        session.execute(
            select(Transaction)
            .join(Transaction.statement)
            .join(Statement.file)
            .options(joinedload(Transaction.statement).joinedload(Statement.file))
            .where(
                Transaction.transaction_date >= period.start_date,
                Transaction.transaction_date <= period.end_date,
            )
            .order_by(Transaction.transaction_date, Transaction.id)
        ).scalars().all()
    )

    contributors: dict[tuple[str, str], list[SummaryTransactionResponse]] = {
        (category.id, subcategory.id): []
        for category in CATEGORY_CATALOG
        for subcategory in category.subcategories
    }
    needs_review: list[SummaryTransactionResponse] = []
    included_eligible_count = 0
    not_applicable_count = 0
    selected_non_expense_count = 0
    unselected_count = 0

    for transaction in transactions:
        eligible = is_expense_reporting_eligible(transaction)
        if not eligible or transaction.category_status == STATUS_NOT_APPLICABLE:
            if not transaction.excluded:
                not_applicable_count += 1
                if transaction.include_in_expenses is True:
                    selected_non_expense_count += 1
            continue
        if transaction.include_in_expenses is not True:
            unselected_count += 1
            continue

        included_eligible_count += 1
        amount = normalized_expense_amount(transaction)
        response = _transaction_response(transaction, amount)
        valid_category = _has_valid_report_category(transaction)
        unresolved_review = (
            transaction.review_status != "REVIEWED"
            and (
                transaction.review_status == "NEEDS_REVIEW"
                or transaction.category_status in {STATUS_NEEDS_REVIEW, "NOT_CATEGORIZED"}
            )
        )
        if unresolved_review or not valid_category:
            needs_review.append(response)
        if not valid_category:
            continue
        contributors[(transaction.main_category, transaction.subcategory)].append(response)

    groups: list[SummaryGroupResponse] = []
    grand_total = Decimal("0.00")
    contributing_count = 0
    source_ids: set[int] = set()
    other_supplies_count = 0

    for category in CATEGORY_CATALOG:
        subcategory_responses: list[SummarySubcategoryResponse] = []
        group_total = Decimal("0.00")
        group_count = 0
        for subcategory in category.subcategories:
            rows = contributors[(category.id, subcategory.id)]
            total = _money(sum((Decimal(row.amount) for row in rows), Decimal("0.00")))
            count = len(rows)
            group_total += total
            group_count += count
            contributing_count += count
            source_ids.update(row.statement_id for row in rows)
            if subcategory.id == BUSINESS_OTHER_SUPPLIES:
                other_supplies_count = count
            subcategory_responses.append(
                SummarySubcategoryResponse(
                    id=subcategory.id,
                    label=subcategory.label,
                    priority=CATEGORY_PRIORITY_INDEX[(category.id, subcategory.id)],
                    transaction_count=count,
                    total=_money_text(total),
                    transactions=rows,
                )
            )
        group_total = _money(group_total)
        grand_total += group_total
        groups.append(
            SummaryGroupResponse(
                id=category.id,
                label=category.label,
                transaction_count=group_count,
                total=_money_text(group_total),
                subcategories=subcategory_responses,
            )
        )

    return ExpenseSummaryResponse(
        period=SummaryPeriodResponse(
            mode=period.mode,
            label=period.label,
            start_date=period.start_date,
            end_date=period.end_date,
            tax_year=period.tax_year,
            available_years=period.available_years,
        ),
        readiness="SUMMARY_READY" if not needs_review else "REVIEW_REQUIRED",
        grand_total=_money_text(grand_total),
        metrics=SummaryMetricsResponse(
            included_eligible_count=included_eligible_count,
            contributing_transaction_count=contributing_count,
            needs_review_count=len(needs_review),
            source_count=len(source_ids),
            not_applicable_count=not_applicable_count,
            selected_non_expense_count=selected_non_expense_count,
            unselected_count=unselected_count,
            other_supplies_count=other_supplies_count,
        ),
        groups=groups,
        needs_review_transactions=needs_review,
    )
