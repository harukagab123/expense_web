from __future__ import annotations

import re

from app.services.transaction_normalization.text import normalized_for_match
from app.services.transaction_type_detection.base import (
    MATCH_CONTAINS,
    MATCH_EXACT,
    MATCH_PREFIX,
    MATCH_REGEX,
    SOURCE_LEARNED_RULE,
    SOURCE_UNRESOLVED,
    STATUS_CLASSIFIED,
    STATUS_NEEDS_REVIEW,
    TYPE_UNKNOWN,
    TypeClassificationInput,
    TypeClassificationResult,
    UserTypeRule,
)
from app.services.transaction_type_detection.rules import match_known_type_rule, suggested_include_for_type


MATCH_TYPE_PRIORITY = {
    MATCH_EXACT: 0,
    MATCH_PREFIX: 1,
    MATCH_CONTAINS: 2,
    MATCH_REGEX: 3,
}


def classify_transaction_type(
    classification_input: TypeClassificationInput,
    user_rules: list[UserTypeRule] | None = None,
) -> TypeClassificationResult:
    user_rule_result = _match_user_rule(classification_input, user_rules or [])
    if user_rule_result is not None:
        return user_rule_result

    known_result = match_known_type_rule(classification_input)
    if known_result is not None:
        return known_result

    return TypeClassificationResult(
        transaction_type=TYPE_UNKNOWN,
        confidence=0.2,
        source=SOURCE_UNRESOLVED,
        status=STATUS_NEEDS_REVIEW,
        suggested_include=suggested_include_for_type(TYPE_UNKNOWN, classification_input.direction),
    )


def _match_user_rule(
    classification_input: TypeClassificationInput,
    rules: list[UserTypeRule],
) -> TypeClassificationResult | None:
    raw = normalized_for_match(classification_input.transaction_detail)
    sorted_rules = sorted(
        rules,
        key=lambda rule: (MATCH_TYPE_PRIORITY.get(rule.match_type, 9), -len(rule.pattern), rule.pattern),
    )

    for rule in sorted_rules:
        if not _matches_rule(raw, rule):
            continue
        status = STATUS_CLASSIFIED if rule.transaction_type != TYPE_UNKNOWN else STATUS_NEEDS_REVIEW
        return TypeClassificationResult(
            transaction_type=rule.transaction_type,
            confidence=0.98,
            source=SOURCE_LEARNED_RULE,
            status=status,
            suggested_include=suggested_include_for_type(rule.transaction_type, classification_input.direction),
            rule_id=rule.id,
        )
    return None


def _matches_rule(value: str, rule: UserTypeRule) -> bool:
    if rule.match_type == MATCH_EXACT:
        return value == rule.pattern
    if rule.match_type == MATCH_PREFIX:
        return value.startswith(rule.pattern)
    if rule.match_type == MATCH_CONTAINS:
        return rule.pattern in value
    if rule.match_type == MATCH_REGEX:
        try:
            return re.search(rule.pattern, value) is not None
        except re.error:
            return False
    return False
