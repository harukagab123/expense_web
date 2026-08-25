from __future__ import annotations

from dataclasses import dataclass


SOURCE_RULE = "RULE"
SOURCE_LEARNED_RULE = "LEARNED_RULE"
SOURCE_USER_EDITED = "USER_EDITED"
SOURCE_UNRESOLVED = "UNRESOLVED"

STATUS_NOT_NORMALIZED = "NOT_NORMALIZED"
STATUS_NORMALIZED = "NORMALIZED"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_USER_CONFIRMED = "USER_CONFIRMED"

MATCH_EXACT = "EXACT"
MATCH_PREFIX = "PREFIX"
MATCH_CONTAINS = "CONTAINS"
MATCH_REGEX = "REGEX"


@dataclass(frozen=True)
class NormalizationResult:
    normalized_name: str | None
    confidence: float
    source: str
    status: str
    rule_id: int | None = None


@dataclass(frozen=True)
class UserNormalizationRule:
    id: int
    pattern: str
    normalized_name: str
    match_type: str
