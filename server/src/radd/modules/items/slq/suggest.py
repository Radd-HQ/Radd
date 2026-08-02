"""SLQ suggest (spec 12): assembly behind GET /items/slq/suggest.

`suggest_context.detect` says WHAT the cursor position wants, the catalog /
field registry / `suggest_values` say what exists; this module authorizes the
scope, filters by the typed partial, ranks (case-insensitive prefix before
contains, then alphabetical — sentinels lead their list), caps at
MAX_SUGGESTIONS, and renders quoting-aware `insert` values that splice verbatim
over [replace_from, cursor). The response contract is FROZEN — frontends build
against it.
"""

import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.fields import service as fields_service
from radd.modules.fields.models import FieldDefinition
from radd.modules.fields.types import FieldType
from radd.modules.projects import service as projects_service

from ..filters import NONE_LITERAL
from .catalog import BUILTIN_OPS, CF_OPS, ME_LITERAL, FieldOps, SlqField
from .lexer import _ESCAPE, CompareOp, _is_word_char
from .parser import RESERVED_WORDS
from .suggest_context import Detection, KeywordSuggestion, Offer, SuggestContext, detect
from .suggest_values import (
    MAX_SUGGESTIONS,
    Candidate,
    SuggestDetail,
    SuggestScope,
    value_candidates,
)

DEFAULT_QUOTE = '"'
_SENTINEL_WORDS = frozenset({ME_LITERAL, NONE_LITERAL})
_BUILTIN_NAMES = frozenset(field.value for field in SlqField)

# Match ranks: prefix beats contains (then alphabetical on the value).
_MATCH_PREFIX = 0
_MATCH_CONTAINS = 1


class Suggestion(BaseModel):
    value: str
    insert: str  # spliced verbatim over [replace_from, cursor); "" = non-insertable hint
    label: str
    detail: str


class SuggestResponse(BaseModel):
    context: SuggestContext
    replace_from: int  # offset where the token being completed starts (== cursor if fresh)
    field: str | None = None  # set when context is operator/value
    suggestions: list[Suggestion]


async def suggest(
    session: AsyncSession,
    *,
    actor: User,
    project_id: uuid.UUID | None,
    q: str,
    cursor: int | None,
) -> SuggestResponse:
    """Authorize the scope (project -> item.read on it; else any active member),
    load the registry in scope, and assemble suggestions for the cursor position."""
    if project_id is not None:
        project = await projects_service.get_project(session, project_id)
        await authz.require(session, actor, Permission.ITEM_READ, project=project)
        scope = SuggestScope(project=project)
        definitions = await fields_service.definitions_for_project(session, project)
    else:
        await authz.require(session, actor, Permission.ITEM_READ)
        scope = SuggestScope()
        definitions = await fields_service.list_fields(session)
    definitions_by_key: dict[str, FieldDefinition] = {}
    for definition in definitions:
        definitions_by_key.setdefault(definition.key, definition)
    return await suggestions_for(
        session, q=q, cursor=cursor, scope=scope, definitions_by_key=definitions_by_key
    )


async def suggestions_for(
    session: AsyncSession,
    *,
    q: str,
    cursor: int | None,
    scope: SuggestScope,
    definitions_by_key: dict[str, FieldDefinition],
) -> SuggestResponse:
    """Pure assembly (authorization already done): detect -> enumerate -> rank."""
    position = len(q) if cursor is None else min(max(cursor, 0), len(q))
    detection = detect(q, position)
    candidates = await _candidates(session, detection, scope, definitions_by_key)
    if detection.quote is not None:  # inside quotes only literals keep their meaning
        candidates = [c for c in candidates if c.literal and c.insertable]
    in_play = detection.context in (SuggestContext.OPERATOR, SuggestContext.VALUE)
    return SuggestResponse(
        context=detection.context,
        replace_from=detection.replace_from,
        field=detection.field if in_play else None,
        suggestions=_assemble(detection, candidates),
    )


async def _candidates(
    session: AsyncSession,
    detection: Detection,
    scope: SuggestScope,
    definitions_by_key: dict[str, FieldDefinition],
) -> list[Candidate]:
    match detection.offer:
        case Offer.FIELDS:
            fields = _field_candidates(definitions_by_key, sortable_only=False)
            return fields + _keyword_candidates(detection)
        case Offer.SORTABLE_FIELDS:
            return _field_candidates(definitions_by_key, sortable_only=True)
        case Offer.OPERATORS:
            return _operator_candidates(detection.field or "", definitions_by_key)
        case Offer.VALUES:
            return await value_candidates(
                session, scope, detection.field or "", detection.partial, definitions_by_key
            )
        case Offer.KEYWORDS:
            return _keyword_candidates(detection)
    return []


def _filterable(ops: FieldOps) -> bool:
    """A field usable in a WHERE comparison (has compare / IN / IS EMPTY ops)."""
    return bool(ops.compare) or ops.membership or ops.empty


def _field_candidates(
    definitions_by_key: dict[str, FieldDefinition], *, sortable_only: bool
) -> list[Candidate]:
    candidates = [
        Candidate(field.value, detail=SuggestDetail.FIELD, literal=False)
        for field in SlqField
        # ORDER BY: sortable fields only; field context: filterable fields only
        # (excludes sort-only `rank`, which has no compare/membership/empty ops).
        if (BUILTIN_OPS[field].sortable if sortable_only else _filterable(BUILTIN_OPS[field]))
    ]
    for key, definition in definitions_by_key.items():
        if not _reachable_key(key):  # shadowed/keyword-spelled cf keys can't be queried
            continue
        field_type = FieldType(definition.type)
        if sortable_only and not CF_OPS[field_type].sortable:
            continue
        candidates.append(
            Candidate(key, detail=f"{definition.name} ({field_type.value})", literal=False)
        )
    return candidates


def _reachable_key(key: str) -> bool:
    return (
        key.lower() not in RESERVED_WORDS
        and key not in _BUILTIN_NAMES
        and bool(key)
        and all(_is_word_char(char) for char in key)
    )


def _ops_for(field: str, definitions_by_key: dict[str, FieldDefinition]) -> FieldOps | None:
    try:
        return BUILTIN_OPS[SlqField(field)]
    except ValueError:
        definition = definitions_by_key.get(field)
        return None if definition is None else CF_OPS[FieldType(definition.type)]


def _operator_candidates(
    field: str, definitions_by_key: dict[str, FieldDefinition]
) -> list[Candidate]:
    ops = _ops_for(field, definitions_by_key)
    if ops is None:  # unknown field: context still reported, nothing to offer
        return []

    def op(value: str) -> Candidate:
        return Candidate(value, detail=SuggestDetail.OPERATOR, literal=False)

    candidates = [op(compare.value) for compare in CompareOp if compare in ops.compare]
    if ops.membership:
        candidates += [op(KeywordSuggestion.IN), op(KeywordSuggestion.NOT_IN)]
    if ops.empty:
        candidates += [op(KeywordSuggestion.IS_EMPTY), op(KeywordSuggestion.IS_NOT_EMPTY)]
    return candidates


def _keyword_candidates(detection: Detection) -> list[Candidate]:
    detail = (
        SuggestDetail.OPERATOR
        if detection.context is SuggestContext.OPERATOR
        else SuggestDetail.KEYWORD
    )
    return [Candidate(keyword.value, detail=detail, literal=False) for keyword in detection.keywords]


# --- filtering, ranking, quoting ---


def _assemble(detection: Detection, candidates: list[Candidate]) -> list[Suggestion]:
    partial = detection.partial.lower()
    ranked: list[tuple[int, int, str, Candidate]] = []
    for candidate in candidates:
        match_rank = _match(candidate, partial)
        if match_rank is None:
            continue
        ranked.append((candidate.tier, match_rank, candidate.value.lower(), candidate))
    ranked.sort(key=lambda entry: entry[:3])
    # Only value context is unbounded (labels/users/item keys); field/operator/keyword
    # sets are bounded and must return in full so no field is unreachable by prefix typing.
    limited = ranked[:MAX_SUGGESTIONS] if detection.context is SuggestContext.VALUE else ranked
    return [_suggestion(candidate, detection) for *_, candidate in limited]


def _match(candidate: Candidate, partial: str) -> int | None:
    """Best rank across value and label; None = filtered out. Hints always show."""
    if not candidate.insertable or not partial:
        return _MATCH_PREFIX
    ranks = [
        rank
        for text in (candidate.value, candidate.label or candidate.value)
        if (rank := _text_match(text.lower(), partial)) is not None
    ]
    return min(ranks, default=None)


def _text_match(text: str, partial: str) -> int | None:
    if text.startswith(partial):
        return _MATCH_PREFIX
    if partial in text:
        return _MATCH_CONTAINS
    return None


def _suggestion(candidate: Candidate, detection: Detection) -> Suggestion:
    return Suggestion(
        value=candidate.value,
        insert=_insert(candidate, detection),
        label=candidate.label or candidate.value,
        detail=candidate.detail,
    )


def _insert(candidate: Candidate, detection: Detection) -> str:
    if not candidate.insertable:
        return ""
    if detection.quote is not None:  # the user opened a quote: close it, same char
        return _quoted(candidate.value, detection.quote)
    if (
        detection.context is SuggestContext.VALUE
        and candidate.literal
        and _needs_quotes(candidate.value)
    ):
        return _quoted(candidate.value, DEFAULT_QUOTE)
    return candidate.value


def _needs_quotes(text: str) -> bool:
    """Spaces/punctuation, keyword spellings, and bare-sentinel collisions must quote."""
    if not text or not all(_is_word_char(char) for char in text):
        return True
    return text.lower() in RESERVED_WORDS or text in _SENTINEL_WORDS


def _quoted(text: str, quote: str) -> str:
    escaped = text.replace(_ESCAPE, _ESCAPE * 2).replace(quote, _ESCAPE + quote)
    return f"{quote}{escaped}{quote}"
