from __future__ import annotations

import re

from app.services.transaction_normalization.base import (
    MATCH_CONTAINS,
    MATCH_EXACT,
    MATCH_PREFIX,
    MATCH_REGEX,
    NormalizationResult,
    SOURCE_LEARNED_RULE,
    SOURCE_UNRESOLVED,
    STATUS_NEEDS_REVIEW,
    STATUS_NORMALIZED,
    UserNormalizationRule,
)
from app.services.transaction_normalization.rules import match_known_rule
from app.services.transaction_normalization.text import conservative_cleanup, looks_unresolved, normalized_for_match


RULE_PRIORITY = {
    MATCH_EXACT: 1,
    MATCH_PREFIX: 2,
    MATCH_CONTAINS: 3,
    MATCH_REGEX: 4,
}


def normalize_transaction_detail(
    transaction_detail: str,
    user_rules: list[UserNormalizationRule] | None = None,
) -> NormalizationResult:
    normalized = normalized_for_match(transaction_detail)
    if not normalized:
        return NormalizationResult(None, 0.0, SOURCE_UNRESOLVED, STATUS_NEEDS_REVIEW)

    user_rule_result = _match_user_rule(normalized, user_rules or [])
    if user_rule_result is not None:
        return user_rule_result

    known_rule_result = match_known_rule(normalized)
    if known_rule_result is not None:
        return known_rule_result

    if looks_unresolved(normalized):
        return NormalizationResult(None, 0.2, SOURCE_UNRESOLVED, STATUS_NEEDS_REVIEW)

    cleaned = conservative_cleanup(normalized)
    if cleaned is None:
        return NormalizationResult(None, 0.25, SOURCE_UNRESOLVED, STATUS_NEEDS_REVIEW)

    return NormalizationResult(
        normalized_name=cleaned,
        confidence=0.66,
        source=SOURCE_UNRESOLVED,
        status=STATUS_NEEDS_REVIEW,
    )


def _match_user_rule(normalized_detail: str, rules: list[UserNormalizationRule]) -> NormalizationResult | None:
    ordered_rules = sorted(
        rules,
        key=lambda rule: (RULE_PRIORITY.get(rule.match_type, 99), -len(rule.pattern)),
    )
    for rule in ordered_rules:
        pattern = normalized_for_match(rule.pattern)
        matched = False
        if rule.match_type == MATCH_EXACT:
            matched = normalized_detail == pattern
        elif rule.match_type == MATCH_PREFIX:
            matched = normalized_detail.startswith(pattern)
        elif rule.match_type == MATCH_CONTAINS:
            matched = pattern in normalized_detail
        elif rule.match_type == MATCH_REGEX:
            try:
                matched = re.search(rule.pattern, normalized_detail, flags=re.IGNORECASE) is not None
            except re.error:
                matched = False

        if matched:
            return NormalizationResult(
                normalized_name=rule.normalized_name,
                confidence=0.98,
                source=SOURCE_LEARNED_RULE,
                status=STATUS_NORMALIZED,
                rule_id=rule.id,
            )
    return None
