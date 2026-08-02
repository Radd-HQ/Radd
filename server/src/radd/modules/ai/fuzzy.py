"""Closest-value matching for NL→SLQ repair (spec 103 addendum) — pure.

"jimmy" must find "Jimmy Lee Barlow". Short proper names are a LEXICAL
problem, not a semantic one, so this is deterministic token-aware string
similarity (stdlib difflib), not embeddings: no model warm-up, no drift, works
with the AI embeddings role off, and trivially unit-testable. Diacritics fold
("rené" finds "René") and matching is case-insensitive.

The scorer prefers, in order: the whole string, an exact word, a word prefix
("jim" → "Jimmy …"), then fuzzy ratios — so a first name beats a vaguely
similar full string.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

# Below this, "closest" is a guess, not a match — leave the value alone and let
# the ordinary compile error surface.
MATCH_THRESHOLD = 0.62


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return stripped.casefold().strip()


def _tokens(text: str) -> list[str]:
    token, out = [], []
    for ch in text:
        if ch.isalnum():
            token.append(ch)
        elif token:
            out.append("".join(token))
            token = []
    if token:
        out.append("".join(token))
    return out


def score(query: str, candidate: str) -> float:
    """0..1 — how plausibly `candidate` is what the user meant by `query` (pure)."""
    q, c = normalize(query), normalize(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    best = SequenceMatcher(None, q, c).ratio() * 0.8
    for position, token in enumerate(_tokens(c)):
        # "laurent" means the person CALLED Laurent before anyone whose surname
        # matches — a small first-token edge breaks exactly that tie.
        first_bonus = 0.01 if position == 0 else 0.0
        if q == token:
            best = max(best, 0.95 + first_bonus)
        elif token.startswith(q) and len(q) >= 3:
            best = max(best, 0.8 + 0.1 * (len(q) / len(token)) + first_bonus)
        else:
            best = max(best, SequenceMatcher(None, q, token).ratio() * 0.85)
    # Multi-word queries ("jimmy lee") get credit for covering candidate words.
    query_tokens = _tokens(q)
    if len(query_tokens) > 1:
        candidate_tokens = set(_tokens(c))
        covered = sum(1 for token in query_tokens if token in candidate_tokens)
        best = max(best, 0.6 + 0.35 * (covered / len(query_tokens)) if covered else best)
    return min(best, 0.99)  # only a verbatim value is a perfect match


@dataclass(frozen=True)
class Match:
    value: str
    confidence: float


def best_match(query: str, candidates: Iterable[str]) -> Match | None:
    """The closest candidate above the threshold, else None (pure,
    deterministic: ties break toward the earlier candidate)."""
    top: Match | None = None
    for candidate in candidates:
        value = score(query, candidate)
        if value >= MATCH_THRESHOLD and (top is None or value > top.confidence):
            top = Match(value=candidate, confidence=value)
    return top
