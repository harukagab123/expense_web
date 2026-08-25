from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.transaction_categorization.base import (
    AUTO_CAR_PAYMENT,
    AUTO_GAS,
    AUTO_INSURANCE,
    AUTO_MAINTENANCE,
    AUTO_PARKING,
    AUTO_TIRES,
    AUTO_TOLLS,
    BUSINESS_ADVERTISING,
    BUSINESS_DONATIONS,
    BUSINESS_EDUCATION_LEARNING,
    BUSINESS_GOVERNMENT,
    BUSINESS_INTEREST_OTHER,
    BUSINESS_LEGAL_PROFESSIONAL,
    BUSINESS_MATERIALS,
    BUSINESS_MEDICAL,
    BUSINESS_OFFICE_EXPENSE,
    BUSINESS_OTHER_SUPPLIES,
    BUSINESS_TOTAL_MEALS,
    BUSINESS_TRANSPORTATION,
    BUSINESS_TRAVEL,
    CategoryClassificationInput,
    CategoryClassificationResult,
    HOME_RENT,
    HOME_REPAIRS_MAINTENANCE,
    HOME_TELECOM_INTERNET,
    HOME_UTILITIES,
    MAIN_AUTO_EXPENSE,
    MAIN_BUSINESS_USE_HOME,
    MAIN_PERSONAL_INTERNAL,
    MAIN_PROFIT_LOSS_BUSINESS,
    STATUS_NEEDS_REVIEW,
    UNCATEGORIZED,
    categorized_result,
    is_category_eligible,
    not_applicable_result,
    uncategorized_result,
)
from app.services.transaction_normalization.text import normalized_for_match


@dataclass(frozen=True)
class DeterministicCategoryRule:
    main_category: str
    subcategory: str
    confidence: float
    patterns: tuple[re.Pattern[str], ...]
    status: str | None = None


EXPENSE_RULES: tuple[DeterministicCategoryRule, ...] = (
    DeterministicCategoryRule(
        MAIN_AUTO_EXPENSE,
        AUTO_PARKING,
        0.93,
        (re.compile(r"\bPARKING\b"), re.compile(r"\bPARKMOBILE\b"), re.compile(r"\bPARK\s+METER\b")),
    ),
    DeterministicCategoryRule(
        MAIN_AUTO_EXPENSE,
        AUTO_TOLLS,
        0.94,
        (re.compile(r"\bFASTRAK\b"), re.compile(r"\bTOLL\s+ROAD\b"), re.compile(r"\bBRIDGE\s+TOLL\b")),
    ),
    DeterministicCategoryRule(
        MAIN_AUTO_EXPENSE,
        AUTO_TIRES,
        0.95,
        (re.compile(r"\bAMERICA'?S\s+TIRE\b"), re.compile(r"\bDISCOUNT\s+TIRE\b"), re.compile(r"\bTIRE(S)?\b")),
    ),
    DeterministicCategoryRule(
        MAIN_AUTO_EXPENSE,
        AUTO_MAINTENANCE,
        0.9,
        (
            re.compile(r"\bJIFFY\s+LUBE\b"),
            re.compile(r"\bAUTO\s+REPAIR\b"),
            re.compile(r"\bOIL\s+CHANGE\b"),
            re.compile(r"\bMECHANIC\b"),
            re.compile(r"\bBRAKE\s+SERVICE\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_AUTO_EXPENSE,
        AUTO_CAR_PAYMENT,
        0.84,
        (
            re.compile(r"\bAUTO\s+LOAN\b"),
            re.compile(r"\bVEHICLE\s+LOAN\b"),
            re.compile(r"\bCAR\s+LOAN\b"),
            re.compile(r"\bHONDA\s+FINANCIAL\b"),
            re.compile(r"\bTOYOTA\s+FINANCIAL\b"),
            re.compile(r"\bLEASE\s+PAYMENT\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_AUTO_EXPENSE,
        AUTO_INSURANCE,
        0.78,
        (
            re.compile(r"\bAUTO\s+INSURANCE\b"),
            re.compile(r"\bGEICO\b"),
            re.compile(r"\bSTATE\s+FARM\b.*\bAUTO\b"),
            re.compile(r"\bPROGRESSIVE\b.*\bAUTO\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_AUTO_EXPENSE,
        AUTO_GAS,
        0.98,
        (
            re.compile(r"\bCHEVRON\b"),
            re.compile(r"\bSHELL\b"),
            re.compile(r"\bARCO\b"),
            re.compile(r"(?:^|\b)76(?:\b|$)"),
            re.compile(r"\bCOSTCO\b.*\bGAS\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_BUSINESS_USE_HOME,
        HOME_TELECOM_INTERNET,
        0.82,
        (
            re.compile(r"\bCOMCAST\b"),
            re.compile(r"\bXFINITY\b"),
            re.compile(r"\bAT&T\b.*\bINTERNET\b"),
            re.compile(r"\bATT\b.*\bINTERNET\b"),
            re.compile(r"\bVERIZON\b.*\bINTERNET\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_BUSINESS_USE_HOME,
        HOME_UTILITIES,
        0.82,
        (
            re.compile(r"\bPG&E\b"),
            re.compile(r"\bPGE\b"),
            re.compile(r"\bELECTRIC\s+UTILITY\b"),
            re.compile(r"\bWATER\s+UTILITY\b"),
            re.compile(r"\bGAS\s+UTILITY\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_BUSINESS_USE_HOME,
        HOME_RENT,
        0.85,
        (re.compile(r"\bRENT\b"), re.compile(r"\bAPARTMENT\s+RENT\b")),
    ),
    DeterministicCategoryRule(
        MAIN_BUSINESS_USE_HOME,
        HOME_REPAIRS_MAINTENANCE,
        0.74,
        (
            re.compile(r"\bPLUMBER\b"),
            re.compile(r"\bHANDYMAN\b"),
            re.compile(r"\bREPAIR\s+SERVICE\b"),
            re.compile(r"\bHARDWARE\s+REPAIR\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_OFFICE_EXPENSE,
        0.91,
        (
            re.compile(r"\bOFFICE\s+DEPOT\b"),
            re.compile(r"\bSTAPLES\b"),
            re.compile(r"\bADOBE\b.*\b(?:ACROBAT|CREATIVE|SUBSCRIPTION)\b"),
            re.compile(r"\bMICROSOFT\s+365\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_ADVERTISING,
        0.88,
        (
            re.compile(r"\bMETA\s+ADS?\b"),
            re.compile(r"\bGOOGLE\s+ADS?\b"),
            re.compile(r"\bYELP\b.*\bADVERTISING\b"),
            re.compile(r"\bMARKETING\s+SERVICE\b"),
            re.compile(r"\bPRINTING\b.*\bMARKETING\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_LEGAL_PROFESSIONAL,
        0.88,
        (
            re.compile(r"\bATTORNEY\b"),
            re.compile(r"\bLAW\s+OFFICE\b"),
            re.compile(r"\bCPA\b"),
            re.compile(r"\bACCOUNTANT\b"),
            re.compile(r"\bBOOKKEEPING\b"),
            re.compile(r"\bCONSULTING\s+FIRM\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_MATERIALS,
        0.82,
        (
            re.compile(r"\bLUMBER\b"),
            re.compile(r"\bBUILDING\s+MATERIAL"),
            re.compile(r"\bCONSTRUCTION\s+SUPPLY\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_OTHER_SUPPLIES,
        0.76,
        (re.compile(r"\bBUSINESS\s+SUPPL(?:Y|IES)\b"), re.compile(r"\bJANITORIAL\s+SUPPL(?:Y|IES)\b")),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_TRAVEL,
        0.72,
        (
            re.compile(r"\bAIRLINE\b"),
            re.compile(r"\bHOTEL\b"),
            re.compile(r"\bTRAVEL\s+BOOKING\b"),
            re.compile(r"\bDELTA\s+AIR\b"),
            re.compile(r"\bUNITED\s+AIRLINES\b"),
            re.compile(r"\bSOUTHWEST\s+AIR\b"),
        ),
        status=STATUS_NEEDS_REVIEW,
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_TOTAL_MEALS,
        0.64,
        (
            re.compile(r"\bRESTAURANT\b"),
            re.compile(r"\bCAFE\b"),
            re.compile(r"\bDINER\b"),
            re.compile(r"\bSTARBUCKS\b"),
        ),
        status=STATUS_NEEDS_REVIEW,
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_TRANSPORTATION,
        0.72,
        (
            re.compile(r"\bUBER\b"),
            re.compile(r"\bLYFT\b"),
            re.compile(r"\bTAXI\b"),
            re.compile(r"\bPUBLIC\s+TRANSIT\b"),
        ),
        status=STATUS_NEEDS_REVIEW,
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_GOVERNMENT,
        0.76,
        (re.compile(r"\bGOVERNMENT\b"), re.compile(r"\bCITY\s+FEE\b"), re.compile(r"\bCOUNTY\s+FEE\b")),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_DONATIONS,
        0.76,
        (re.compile(r"\bDONATION\b"), re.compile(r"\bCHARITY\b"), re.compile(r"\bCHARITABLE\b")),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_MEDICAL,
        0.76,
        (
            re.compile(r"\bKAISER\b"),
            re.compile(r"\bKAISERDUES\b"),
            re.compile(r"\bMEDICAL\s+CLINIC\b"),
            re.compile(r"\bPHARMACY\b"),
            re.compile(r"\bHEALTH\s+PROVIDER\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_EDUCATION_LEARNING,
        0.78,
        (
            re.compile(r"\bCOURSE\b"),
            re.compile(r"\bTRAINING\b"),
            re.compile(r"\bCERTIFICATION\b"),
            re.compile(r"\bUDEMY\b"),
            re.compile(r"\bCOURSERA\b"),
        ),
    ),
)

AMBIGUOUS_EXPENSE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAMAZON\b"),
    re.compile(r"\bAMZN\b"),
    re.compile(r"^\bCOSTCO\b(?!.*\bGAS\b)"),
)


def match_known_category_rule(
    classification_input: CategoryClassificationInput,
) -> CategoryClassificationResult:
    if not is_category_eligible(classification_input.transaction_type, classification_input.direction):
        return not_applicable_result()

    text = _combined_text(classification_input)

    if classification_input.transaction_type == "BANK_FEE":
        return uncategorized_result(confidence=0.45)
    if classification_input.transaction_type == "INTEREST":
        return categorized_result(
            MAIN_PROFIT_LOSS_BUSINESS,
            BUSINESS_INTEREST_OTHER,
            0.82,
        )

    for rule in EXPENSE_RULES:
        if _matches_any(text, rule.patterns):
            return categorized_result(
                rule.main_category,
                rule.subcategory,
                rule.confidence,
                status=rule.status,
            )

    if _matches_any(text, AMBIGUOUS_EXPENSE_PATTERNS):
        return uncategorized_result(confidence=0.35)

    return uncategorized_result(confidence=0.35)


def _combined_text(classification_input: CategoryClassificationInput) -> str:
    values = [
        classification_input.normalized_name or "",
        classification_input.transaction_detail,
    ]
    return normalized_for_match(" ".join(values))


def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(value) is not None for pattern in patterns)
