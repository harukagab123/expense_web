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
    BUSINESS_BANK_MEMBERSHIP,
    BUSINESS_OFFICE_EXPENSE,
    BUSINESS_OTHER_SUPPLIES,
    BUSINESS_TOTAL_MEALS,
    BUSINESS_TRANSPORTATION,
    BUSINESS_TRAVEL,
    CATEGORY_PRIORITY,
    CategoryClassificationInput,
    CategoryClassificationResult,
    HOME_INSURANCE,
    HOME_OTHER_EXPENSE,
    HOME_RENT,
    HOME_REPAIRS_MAINTENANCE,
    HOME_TELECOM_INTERNET,
    HOME_UTILITIES,
    MAIN_AUTO_EXPENSE,
    MAIN_BUSINESS_USE_HOME,
    MAIN_PROFIT_LOSS_BUSINESS,
    STATUS_NEEDS_REVIEW,
    categorized_result,
    is_category_eligible,
    not_applicable_result,
)
from app.services.transaction_normalization.text import normalized_for_match


MINIMUM_APPLICABILITY_CONFIDENCE = 0.50


@dataclass(frozen=True)
class DeterministicCategoryRule:
    main_category: str
    subcategory: str
    confidence: float
    patterns: tuple[re.Pattern[str], ...]
    weak_patterns: tuple[re.Pattern[str], ...] = ()
    weak_confidence: float = 0.55
    status: str | None = None


@dataclass(frozen=True)
class CategoryCandidateEvaluation:
    priority: int
    main_category: str
    subcategory: str
    score: float
    applicable: bool
    reason: str


EXPENSE_RULES: tuple[DeterministicCategoryRule, ...] = (
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
            re.compile(r"\bSAFEWAY\s+FUEL\b"),
        ),
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
        AUTO_PARKING,
        0.93,
        (
            re.compile(r"\bPARKING\b"),
            re.compile(r"\bPARKMOBILE\b"),
            re.compile(r"\bPARK\s+METER\b"),
            re.compile(r"\bPARKING\s+GARAGE\b"),
            re.compile(r"\bPARKSMART\b"),
        ),
        weak_patterns=(re.compile(r"\bPRK\b"),),
    ),
    DeterministicCategoryRule(
        MAIN_AUTO_EXPENSE,
        AUTO_TIRES,
        0.95,
        (re.compile(r"\bAMERICA'?S\s+TIRE\b"), re.compile(r"\bDISCOUNT\s+TIRE\b"), re.compile(r"\bTIRE(S)?\b")),
    ),
    DeterministicCategoryRule(
        MAIN_AUTO_EXPENSE,
        AUTO_TOLLS,
        0.94,
        (
            re.compile(r"\bFASTRAK\b"),
            re.compile(r"\bTOLL(?:S|\s+ROAD)?\b"),
            re.compile(r"\bBRIDGE\s+TOLL\b"),
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
            re.compile(r"\bHONDA\s+FINANC(?:E|IAL)\b.*\b(?:VEHICLE\s+)?PMT\b"),
            re.compile(r"\bLEASE\s+PAYMENT\b"),
            re.compile(r"\bAUTO\s+LEASE\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_BUSINESS_USE_HOME,
        HOME_INSURANCE,
        0.86,
        (
            re.compile(r"\bHOMEOWNERS?\s+INSURANCE\b"),
            re.compile(r"\bRENTERS?\s+INSURANCE\b"),
            re.compile(r"\bPROPERTY\s+INSURANCE\b"),
            re.compile(r"\bHOME\s+INSURANCE\b"),
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
            re.compile(r"\bVERIZON\s+FIOS\b"),
            re.compile(r"\bSPECTRUM\b.*\bINTERNET\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_BUSINESS_USE_HOME,
        HOME_UTILITIES,
        0.82,
        (
            re.compile(r"\bPG&E\b"),
            re.compile(r"\bPGE\b"),
            re.compile(r"\bPGANDE\b"),
            re.compile(r"\bELECTRIC\s+UTILITY\b"),
            re.compile(r"\bWATER\s+UTILITY\b"),
            re.compile(r"\bGAS\s+UTILITY\b"),
            re.compile(r"\bWATER\s+BILL\b"),
            re.compile(r"\b(?:MUNICIPAL\s+)?ELECTRIC\s+BILL\b"),
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
            re.compile(r"\bHOME\s+DEPOT\b.*\bPLUMBING\s+PARTS?\b"),
            re.compile(r"\bHANDYMAN\b"),
            re.compile(r"\bELECTRICAL\s+REPAIR\b"),
            re.compile(r"\bREPAIR\s+SERVICE\b"),
            re.compile(r"\bHARDWARE\s+REPAIR\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_BUSINESS_USE_HOME,
        HOME_OTHER_EXPENSE,
        0.66,
        (
            re.compile(r"\bHOME\s+OFFICE\s+PEST\s+CONTROL\b"),
            re.compile(r"\bHOME\s+OFFICE\s+SECURITY\s+MONITORING\b"),
            re.compile(r"\bHOME\s+OFFICE\s+CLEANING\s+SERVICE\b"),
        ),
        status=STATUS_NEEDS_REVIEW,
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_OFFICE_EXPENSE,
        0.91,
        (
            re.compile(r"\bOFFICE\s+DEPOT\b"),
            re.compile(r"\bSTAPLES\b"),
            re.compile(r"\bPRINTER\s+(?:INK|PAPER)\b"),
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
            re.compile(r"\bPRINT\s+MARKETING\b"),
            re.compile(r"\bFACEBOOK\s+ADVERTISING\b"),
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
            re.compile(r"\bACCOUNTING\s+FIRM\b"),
            re.compile(r"\bBOOKKEEPING\b"),
            re.compile(r"\bCONSULTING\s+FIRM\b"),
            re.compile(r"\bPROFESSIONAL\s+CONSULTANT\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_MATERIALS,
        0.82,
        (
            re.compile(r"\bLUMBER\b"),
            re.compile(r"\b(?:BUILDING|PROJECT|JOB)\s+MATERIALS?\b"),
            re.compile(r"\bCONSTRUCTION\s+SUPPL(?:Y|IES)\b"),
            re.compile(r"\bCONSTRUCTION\s+MATERIALS?\b"),
            re.compile(r"\bRAW\s+MATERIAL(?:S|\s+SUPPLY)\b"),
            re.compile(r"\bPROJECT\s+(?:CONSTRUCTION\s+)?MATERIAL(?:S|\s+SUPPLY)\b"),
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
            re.compile(r"\bMARRIOTT(?:\s+BONVOY)?\b"),
            re.compile(r"\bZIPAIR\b"),
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
            re.compile(
                r"\b(?:HABIT(?:\s+BURGER)?|PANDA\s+EXPRESS|MCDONALD'?S|BURGER\s+KING|"
                r"DOMINO'?S|SUBWAY|CHEESECAKE\s+FACTORY|BOUDIN(?:\s+BAKERY)?|"
                r"PARIS\s+BAGUETTE|RAMEN|UDON)\b"
            ),
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
            re.compile(r"\bBART\b(?:.*\b(?:TRANSIT|FARE)\b)?"),
        ),
        status=STATUS_NEEDS_REVIEW,
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_GOVERNMENT,
        0.76,
        (
            re.compile(r"\bGOVERNMENT\b"),
            re.compile(r"\bCITY\b.*\b(?:BUSINESS\s+LICENSE|PERMIT)\s+FEE\b"),
            re.compile(r"\bCOUNTY\b.*\b(?:LICENSE|PERMIT)\s+FEE\b"),
            re.compile(r"\bIRS\s+TAX\s+PAYMENT\b"),
            re.compile(r"\bIRS\b.*\b(?:TAX|USATAXPYMT)\b"),
            re.compile(r"\bDMV\s+REGISTRATION\s+FEE\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_DONATIONS,
        0.76,
        (
            re.compile(r"\bDONATION\b"),
            re.compile(r"\bCHARITY\b"),
            re.compile(r"\bCHARITABLE\b"),
            re.compile(r"\bFOUNDATION\s+CONTRIBUTION\b"),
        ),
    ),
    DeterministicCategoryRule(
        MAIN_PROFIT_LOSS_BUSINESS,
        BUSINESS_MEDICAL,
        0.76,
        (
            re.compile(r"\bKAISER\b"),
            re.compile(r"\bKAISERDUES\b"),
            re.compile(r"\bMEDICAL\s+CLINIC\b"),
            re.compile(r"\bDOCTOR\s+OFFICE\b"),
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
            re.compile(r"\bEDUCATION\s+SEMINAR\b"),
        ),
    ),
)

EXPENSE_RULES_BY_CATEGORY = {
    (rule.main_category, rule.subcategory): rule
    for rule in EXPENSE_RULES
}
if len(EXPENSE_RULES_BY_CATEGORY) != len(EXPENSE_RULES):
    raise RuntimeError("Deterministic expense categories must have at most one rule definition.")

def match_known_category_rule(
    classification_input: CategoryClassificationInput,
) -> CategoryClassificationResult:
    result, _evaluations = _evaluate_known_category_rules(classification_input, collect_trace=False)
    return result


def trace_known_category_rules(
    classification_input: CategoryClassificationInput,
) -> tuple[CategoryClassificationResult, tuple[CategoryCandidateEvaluation, ...]]:
    """Return test/debug evidence without exposing verbose traces in the normal UI."""
    return _evaluate_known_category_rules(classification_input, collect_trace=True)


def _evaluate_known_category_rules(
    classification_input: CategoryClassificationInput,
    *,
    collect_trace: bool,
) -> tuple[CategoryClassificationResult, tuple[CategoryCandidateEvaluation, ...]]:
    if not is_category_eligible(classification_input.transaction_type, classification_input.direction):
        return not_applicable_result(), ()

    text = _combined_text(classification_input)
    evaluations: list[CategoryCandidateEvaluation] = []

    for priority, category_pair in enumerate(CATEGORY_PRIORITY, start=1):
        evidence = _candidate_evidence(classification_input, category_pair, text)
        is_fallback = category_pair == (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_OTHER_SUPPLIES)
        if evidence is None and is_fallback:
            evidence = (0.30, STATUS_NEEDS_REVIEW, "final fallback after all 26 specific categories failed")

        confidence = evidence[0] if evidence is not None else 0.0
        applicable = is_fallback or confidence >= MINIMUM_APPLICABILITY_CONFIDENCE
        reason = evidence[2] if evidence is not None else "no supporting evidence"
        if collect_trace:
            evaluations.append(
                CategoryCandidateEvaluation(
                    priority=priority,
                    main_category=category_pair[0],
                    subcategory=category_pair[1],
                    score=confidence,
                    applicable=applicable,
                    reason=reason,
                )
            )
        if evidence is not None and applicable:
            return (
                categorized_result(
                    category_pair[0],
                    category_pair[1],
                    confidence,
                    status=evidence[1],
                ),
                tuple(evaluations),
            )

    raise RuntimeError("Category catalog must end with the Other Supplies fallback.")


def _combined_text(classification_input: CategoryClassificationInput) -> str:
    values = [
        classification_input.normalized_name or "",
        classification_input.transaction_detail,
        classification_input.interpreted_detail or "",
    ]
    return normalized_for_match(" ".join(values))


def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(value) is not None for pattern in patterns)


def _matching_evidence(
    rule: DeterministicCategoryRule,
    text: str,
) -> tuple[float, str | None, str] | None:
    if _matches_any(text, rule.patterns):
        return rule.confidence, rule.status, "strong deterministic pattern"
    if _matches_any(text, rule.weak_patterns):
        return rule.weak_confidence, STATUS_NEEDS_REVIEW, "weak deterministic pattern"
    return None


def _candidate_evidence(
    classification_input: CategoryClassificationInput,
    category_pair: tuple[str, str],
    text: str,
) -> tuple[float, str | None, str] | None:
    if classification_input.transaction_type == "BANK_FEE":
        if category_pair == (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_BANK_MEMBERSHIP):
            return 0.58, STATUS_NEEDS_REVIEW, "BANK_FEE transaction type"
        return None
    if classification_input.transaction_type == "INTEREST":
        if category_pair == (MAIN_PROFIT_LOSS_BUSINESS, BUSINESS_INTEREST_OTHER):
            return 0.82, None, "outflow INTEREST transaction type"
        return None
    rule = EXPENSE_RULES_BY_CATEGORY.get(category_pair)
    return _matching_evidence(rule, text) if rule is not None else None
