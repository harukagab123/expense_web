from __future__ import annotations

from dataclasses import dataclass
import re


TOKEN_RE = re.compile(r"[A-Z0-9]+(?:&[A-Z0-9]+)?")


@dataclass(frozen=True)
class TermDefinition:
    id: int
    term: str
    normalized_meaning: str
    institution: str
    context: str
    confidence: float
    times_confirmed: int = 0


@dataclass(frozen=True)
class TermMatch:
    term_id: int
    term: str
    meaning: str
    institution: str
    confidence: float
    start_token: int
    end_token: int


@dataclass(frozen=True)
class TerminologyInterpretation:
    interpreted_detail: str
    confidence: float
    matches: tuple[TermMatch, ...]


def normalize_institution(value: str | None) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", (value or "").upper()).strip("_")
    return normalized or "GLOBAL"


def tokenize(value: str) -> list[str]:
    return TOKEN_RE.findall((value or "").upper())


def interpret_description(
    transaction_detail: str,
    institution: str,
    definitions: list[TermDefinition],
) -> TerminologyInterpretation:
    tokens = tokenize(transaction_detail)
    if not tokens:
        return TerminologyInterpretation(transaction_detail, 0.0, ())

    institution_key = normalize_institution(institution)
    eligible = [
        definition
        for definition in definitions
        if normalize_institution(definition.institution) in {"GLOBAL", institution_key}
    ]
    eligible.sort(
        key=lambda definition: (
            normalize_institution(definition.institution) != institution_key,
            -len(tokenize(definition.term)),
            -definition.confidence,
            definition.term,
        )
    )

    occupied: set[int] = set()
    matches: list[TermMatch] = []
    for definition in eligible:
        term_tokens = tokenize(definition.term)
        if not term_tokens:
            continue
        for start in range(0, len(tokens) - len(term_tokens) + 1):
            end = start + len(term_tokens)
            if any(index in occupied for index in range(start, end)):
                continue
            if tokens[start:end] != term_tokens:
                continue
            confidence = _effective_confidence(definition, tokens, start, end)
            matches.append(
                TermMatch(
                    term_id=definition.id,
                    term=definition.term,
                    meaning=definition.normalized_meaning,
                    institution=definition.institution,
                    confidence=confidence,
                    start_token=start,
                    end_token=end,
                )
            )
            occupied.update(range(start, end))

    matches.sort(key=lambda match: match.start_token)
    if not matches:
        return TerminologyInterpretation(" ".join(tokens), 0.0, ())

    match_by_start = {match.start_token: match for match in matches}
    interpreted: list[str] = []
    index = 0
    while index < len(tokens):
        match = match_by_start.get(index)
        if match is None:
            interpreted.append(tokens[index])
            index += 1
            continue
        interpreted.extend(match.meaning.split())
        index = match.end_token

    confidence = sum(match.confidence for match in matches) / len(matches)
    return TerminologyInterpretation(" ".join(interpreted), min(0.99, confidence), tuple(matches))


def _effective_confidence(
    definition: TermDefinition,
    tokens: list[str],
    start: int,
    end: int,
) -> float:
    confidence = definition.confidence + min(0.12, definition.times_confirmed * 0.02)
    context_tokens = {token for token in re.split(r"[|, ]+", definition.context.upper()) if token and token != "ANY"}
    if context_tokens:
        neighbors = set(tokens[max(0, start - 2) : min(len(tokens), end + 2)])
        if neighbors & context_tokens:
            confidence += 0.08
    if normalize_institution(definition.institution) != "GLOBAL":
        confidence += 0.03
    return min(0.99, confidence)
