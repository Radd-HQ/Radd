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

States get one more step (RADD-1140): a `state = Fixed` with no lexical
neighbour among the real states is not a typo but a CATEGORY spoken as a
state — it is rewritten to `category = done` through the `STATE_WORDS`
table; a state word that is neither is left alone but REPORTED, so the
explanation says the state does not exist instead of the query quietly
returning nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.fields.models import FieldDefinition
from radd.modules.workflow.types import StateCategory
from radd.modules.ai.types import STATE_WORDS, ImpliedCategory, SlqDialect
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
from radd.modules.items.slq.catalog import SlqField
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

# `state = open` is `category != done`: the not-done words flip the operator.
_FLIPPED_OP = {CompareOp.EQ: CompareOp.NE, CompareOp.NE: CompareOp.EQ}


class RepairKind(StrEnum):
    VALUE = "value"  # the value was swapped for the closest real one
    CATEGORY = "category"  # a state word became the category comparison it meant
    UNKNOWN_STATE = "unknown_state"  # left as written; no state carries that name


@dataclass(frozen=True)
class Repair:
    field: str
    original: str
    replacement: str  # empty for UNKNOWN_STATE — nothing was substituted
    label: str | None  # display name when the value is opaque (user emails)
    kind: RepairKind = RepairKind.VALUE

    def note(self) -> str:
        match self.kind:
            case RepairKind.CATEGORY:
                return f"read '{self.original}' as {self.replacement} (no state by that name)"
            case RepairKind.UNKNOWN_STATE:
                return f"no state named '{self.original}' exists on this tracker"
        shown = f"{self.label} ({self.replacement})" if self.label else self.replacement
        return f"matched '{self.original}' to {shown}"


def _is_state_field(field: str) -> bool:
    """`state`, `epic.state`, `parent.state`, and their `issue.` forms."""
    return field == SlqField.STATE.value or field.endswith(f".{SlqField.STATE.value}")


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

    async def resolve(field: str, value: Value) -> Value | None:
        """The value to emit — itself, or the closest real one (recorded as a
        repair) — or None when the field HAS a candidate set and the value
        matches nothing in it."""
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
            return None  # nothing close
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

    def unknown_state(field: str, value: Value) -> None:
        repairs.append(
            Repair(field, value.text, replacement="", label=None, kind=RepairKind.UNKNOWN_STATE)
        )

    def state_word_as_category(expr: Comparison) -> Comparison:
        """`state = Fixed` → `category = done`; `state = open` → `category != done`.
        A word outside the table stays as written, and is reported."""
        implied = STATE_WORDS.implied(expr.value.text)
        if implied is None:
            unknown_state(expr.field, expr.value)
            return expr
        op = expr.op if implied is ImpliedCategory.DONE else _FLIPPED_OP[expr.op]
        field = expr.field.removesuffix(SlqField.STATE.value) + SlqField.CATEGORY.value
        rewritten = Comparison(
            field,
            op,
            Value(StateCategory.DONE.value, position=expr.value.position),
            expr.field_position,
            expr.op_position,
        )
        repairs.append(
            Repair(
                expr.field,
                expr.value.text,
                replacement=f"{field} {op.value} {StateCategory.DONE.value}",
                label=None,
                kind=RepairKind.CATEGORY,
            )
        )
        return rewritten

    async def fix_expr(expr):
        if isinstance(expr, Comparison):
            if expr.op is CompareOp.CONTAINS:
                return expr  # `~` means substring — a partial value is the point
            resolved = await resolve(expr.field, expr.value)
            if resolved is not None:
                return replace(expr, value=resolved)
            if _is_state_field(expr.field):
                return state_word_as_category(expr)
            return expr  # let the honest empty result stand
        if isinstance(expr, Membership):
            values: list[Value] = []
            for value in expr.values:
                resolved = await resolve(expr.field, value)
                if resolved is None and _is_state_field(expr.field):
                    unknown_state(expr.field, value)
                values.append(value if resolved is None else resolved)
            return replace(expr, values=tuple(values))
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
