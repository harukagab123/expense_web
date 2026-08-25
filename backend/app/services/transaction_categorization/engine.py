from __future__ import annotations

import re

from app.services.transaction_categorization.base import (
    MATCH_CONTAINS,
    MATCH_EXACT,
    MATCH_NORMALIZED_NAME,
    MATCH_PREFIX,
    MATCH_REGEX,
    SOURCE_LEARNED_RULE,
    STATUS_CATEGORIZED,
    STATUS_NEEDS_REVIEW,
    CategoryClassificationInput,
    CategoryClassificationResult,
    UserCategoryRule,
    categorized_result,
    is_category_eligible,
    not_applicable_result,
)
from app.services.transaction_categorization.rules import match_known_category_rule
from app.services.transaction_normalization.text import normalized_for_match


MATCH_TYPE_PRIORITY = {
    MATCH_NORMALIZED_NAME: 0,
    MATCH_EXACT: 1,
    MATCH_PREFIX: 2,
    MATCH_CONTAINS: 3,
    MATCH_REGEX: 4,
}


def categorize_transaction(
    classification_input: CategoryClassificationInput,
    user_rules: list[UserCategoryRule] | None = None,
) -> CategoryClassificationResult:
    if not is_category_eligible(classification_input.transaction_type, classification_input.direction):
        return not_applicable_result()

    user_rule_result = _match_user_rule(classification_input, user_rules or [])
    if user_rule_result is not None:
        return user_rule_result

    return match_known_category_rule(classification_input)


def _match_user_rule(
    classification_input: CategoryClassificationInput,
    rules: list[UserCategoryRule],
) -> CategoryClassificationResult | None:
    raw = normalized_for_match(classification_input.transaction_detail)
    normalized_name = normalized_for_match(classification_input.normalized_name or "")
    sorted_rules = sorted(
        rules,
        key=lambda rule: (MATCH_TYPE_PRIORITY.get(rule.match_type, 9), -len(rule.pattern), rule.pattern),
    )

    for rule in sorted_rules:
        if not _matches_rule(raw, normalized_name, rule):
            continue
        return categorized_result(
            rule.main_category,
            rule.subcategory,
            0.98,
            source=SOURCE_LEARNED_RULE,
            status=STATUS_CATEGORIZED if rule.subcategory != "UNCATEGORIZED" else STATUS_NEEDS_REVIEW,
            rule_id=rule.id,
        )
    return None


def _matches_rule(raw: str, normalized_name: str, rule: UserCategoryRule) -> bool:
    if rule.match_type == MATCH_NORMALIZED_NAME:
        return normalized_name == rule.pattern
    if rule.match_type == MATCH_EXACT:
        return raw == rule.pattern
    if rule.match_type == MATCH_PREFIX:
        return raw.startswith(rule.pattern)
    if rule.match_type == MATCH_CONTAINS:
        return rule.pattern in raw
    if rule.match_type == MATCH_REGEX:
        try:
            return re.search(rule.pattern, raw) is not None
        except re.error:
            return False
    return False
