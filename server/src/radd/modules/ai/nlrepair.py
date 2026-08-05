"""NL→SLQ value repair (spec 103 addendum): make generated queries name REAL things.

The model writes `assignee = jimmy`; the actual account is Jimmy Lee Barlow.
SLQ itself must stay EXACT — a typo in a saved view must never silently match
someone else — so the forgiveness lives HERE, in the NL layer only: a
pre-compile AST walk that resolves every entity value against the live
candidates the autocomplete seam already serves (users, states, labels,
projects, teams, cycles, releases, issue types, custom select options), swaps
in the closest real value, and reports every substitution.

Proactive by necessity: for most entity fields an unknown value COMPILES —
into a correlated subquery that matches nothing — so there is no error to
catch (the silent-empty-result hole this closes). Repaired values are always
re-emitted QUOTED, which both survives spaces and guarantees the replacement
is never re-read as a grammar sentinel.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.fields.models import FieldDefinition
from radd.modules.ai.types import SlqDialect
from radd.modules.items.slq import (
    ME_LITERAL,
    NONE_LITERAL,
    BoolExpr,
    Comparison,
    EmptyCheck,
    Membership,
    NotExpr,
    Query,
    Value,
    is_sentinel,
)
from radd.modules.items.slq.parser import CompareOp
from radd.modules.items.slq.custom import BOOLEAN_WORDS
from radd.modules.items.slq.helpers import DATE_RE, ITEM_KEY_RE, relative_date
from radd.modules.items.slq.suggest_values import Candidate, SuggestScope, value_candidates

from .fuzzy import best_match, normalize

# Plugin-contributed user fields (spec 97) have no autocomplete branch; their
# value language is the same people, so they borrow the assignee candidates.
_CANDIDATE_ALIASES = {"logged_by": "assignee", "commented_by": "assignee"}

# Worklog-dialect bare fields (spec 98) mapped onto item candidate sources;
# `category` has its own source below, the rest have no candidate set.
_WORKLOG_ALIASES = {"author": "assignee", "project": "project"}
_WORKLOG_CATEGORY = "category"

# Item fields reached from the worklog dialect (spec 98 delegation).
_ISSUE_PREFIX = "issue."

# Candidate entries that are grammar, not data — never a repair target.
_SENTINEL_VALUES = frozenset({ME_LITERAL, NONE_LITERAL, "today", "true", "false"})


@dataclass(frozen=True)
class Repair:
    field: str
    original: str
    replacement: str
    label: str | None  # display name when the value is opaque (user emails)

    def note(self) -> str:
        shown = f"{self.label} ({self.replacement})" if self.label else self.replacement
        return f"matched '{self.original}' to {shown}"


async def repair_query(
    session: AsyncSession,
    query: Query,
    *,
    definitions_by_key: dict[str, FieldDefinition],
    dialect: str = "items",
) -> tuple[Query, list[Repair]]:
    """The repaired query + what changed. Values that already name something
    real — or that are sentinels, dates, booleans, item keys, or free text with
    no candidate set — pass through untouched. `dialect="worklog"` resolves the
    timesheet's bare fields (author/category/project) and strips the `issue.`
    prefix off delegated item fields before sourcing candidates."""
    repairs: list[Repair] = []
    cache: dict[str, list[Candidate]] = {}

    async def candidates_for(field: str) -> list[Candidate]:
        source: str | None = field
        if field.startswith(_ISSUE_PREFIX):
            source = field.removeprefix(_ISSUE_PREFIX)
        elif dialect == SlqDialect.WORKLOG.value:
            if field == _WORKLOG_CATEGORY:
                return await category_candidates(session, cache)
            source = _WORKLOG_ALIASES.get(field)  # time/worked_on/note/issue: none
            if source is None:
                return []
        source = _CANDIDATE_ALIASES.get(source, source)
        if source not in cache:
            cache[source] = await value_candidates(
                session, SuggestScope(), source, "", definitions_by_key
            )
        return cache[source]

    async def fix_value(field: str, value: Value) -> Value:
        if _skip(value):
            return value
        candidates = [
            candidate
            for candidate in await candidates_for(field)
            if candidate.insertable and candidate.value not in _SENTINEL_VALUES
        ]
        if not candidates:
            return value  # free-text field, or nothing to match against
        if any(candidate.value == value.text for candidate in candidates):
            return value  # already names something real, verbatim
        best: tuple[Candidate, float] | None = None
        for candidate in candidates:
            scored = _score(value.text, candidate)
            if scored is not None and (best is None or scored > best[1]):
                best = (candidate, scored)
        if best is None:
            return value  # nothing close — let the honest empty result stand
        chosen = best[0]
        repairs.append(
            Repair(
                field=field,
                original=value.text,
                replacement=chosen.value,
                label=chosen.label if chosen.label != chosen.value else None,
            )
        )
        # Quoted: survives spaces AND can never be re-read as a sentinel.
        return replace(value, text=chosen.value, quoted=True)

    def _skip(value: Value) -> bool:
        return (
            is_sentinel(value, ME_LITERAL)
            or is_sentinel(value, NONE_LITERAL)
            or value.text in BOOLEAN_WORDS
            or DATE_RE.match(value.text) is not None
            or relative_date(value, date.today()) is not None
            or ITEM_KEY_RE.match(value.text) is not None
        )

    def _score(text: str, candidate: Candidate) -> float | None:
        # Users carry the display name in `label` — "jimmy" scores against
        # "Jimmy Lee Barlow" and the query gets the email in `value`.
        targets = [candidate.value] + ([candidate.label] if candidate.label else [])
        match = best_match(text, targets)
        if match is None:
            return None
        # A case/diacritic-only difference is still a repair (state names are
        # case-sensitive in SLQ) but always a safe one — give it full marks.
        if any(normalize(target) == normalize(text) for target in targets):
            return 1.0
        return match.confidence

    async def fix_expr(expr):
        if isinstance(expr, Comparison):
            if expr.op is CompareOp.CONTAINS:
                return expr  # `~` means substring — a partial value is the point
            return replace(expr, value=await fix_value(expr.field, expr.value))
        if isinstance(expr, Membership):
            fixed = tuple([await fix_value(expr.field, value) for value in expr.values])
            return replace(expr, values=fixed)
        if isinstance(expr, EmptyCheck):
            return expr
        if isinstance(expr, NotExpr):
            return NotExpr(operand=await fix_expr(expr.operand))
        if isinstance(expr, BoolExpr):
            operands = tuple([await fix_expr(operand) for operand in expr.operands])
            return replace(expr, operands=operands)
        return expr

    if query.where is None:
        return query, []
    fixed_where = await fix_expr(query.where)
    return replace(query, where=fixed_where), repairs


async def category_candidates(
    session: AsyncSession, cache: dict[str, list[Candidate]] | None = None
) -> list[Candidate]:
    """Work-category names (worklog dialect) — deferred import, [] when the
    timelogging module is absent. Public: the NL prompt enumerates these too."""
    if cache is None:
        cache = {}
    key = "__worklog_category__"
    if key not in cache:
        try:
            from radd.modules.timelogging import service as timelogging_service
        except ImportError:
            cache[key] = []
        else:
            names = await timelogging_service.category_names(session)
            cache[key] = [Candidate(name, label=None, detail="") for name in names]
    return cache[key]
