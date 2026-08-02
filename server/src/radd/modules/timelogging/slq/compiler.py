"""Worklog SLQ AST -> SQLAlchemy over `Worklog`.

Reuses the item dialect's lexer, parser and coercion helpers — those are generic
query machinery, nothing in them knows about work items — and supplies only what
is genuinely worklog-shaped: a seven-field catalog and this compiler.

The `issue.<field>` delegation is the design's whole point. Rather than restate
the item field surface here (which would fork and drift), an `issue.` term is
rewritten into an ITEM condition and handed to `items.slq.compile_query`, whose
result is wrapped as `worklog.item_id IN (SELECT id FROM work_items WHERE …)`.
That inherits builtins, custom fields, ancestors, labels and plugin fields
permanently. Delegating PER CONDITION is exact, not an approximation: a worklog
has exactly one issue, so `issue.a AND issue.b` and "one issue matching a AND b"
are the same set.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.items.models import WorkItem
from radd.modules.items.slq import (
    ME_LITERAL,
    BoolExpr,
    BoolOp,
    Comparison,
    Condition,
    EmptyCheck,
    Expr,
    Membership,
    NotExpr,
    Query,
    SlqError,
    check_ops,
    compare,
    compile_query as compile_item_query,
    date_value,
    escape_like,
    is_sentinel,
    negated,
    plain,
    polarity,
    values_of,
)
from radd.modules.items.slq.errors import unknown_field
from radd.modules.items.slq.lexer import CompareOp
from radd.modules.projects.models import Project

from ..duration import DurationError, parse_duration
from ..models import WorkCategory, Worklog
from .catalog import ISSUE_PREFIX, WORKLOG_OPS, WorklogField


@dataclass(frozen=True)
class CompiledWorklogQuery:
    where: ColumnElement[bool] | None


@dataclass(frozen=True)
class _Ctx:
    current_user_id: uuid.UUID
    hours_per_day: int
    days_per_week: int


async def compile_worklog_query(
    session: AsyncSession,
    query: Query,
    *,
    current_user_id: uuid.UUID,
    hours_per_day: int = 8,
    days_per_week: int = 5,
) -> CompiledWorklogQuery:
    """Compile a parsed worklog query. Async because `issue.` terms are compiled
    by the item dialect, which resolves label names and item keys against the
    database."""
    ctx = _Ctx(current_user_id, hours_per_day, days_per_week)
    where = await _expr(session, ctx, query.where) if query.where is not None else None
    return CompiledWorklogQuery(where=where)


async def _expr(session: AsyncSession, ctx: _Ctx, expr: Expr) -> ColumnElement[bool]:
    match expr:
        case BoolExpr():
            parts = [await _expr(session, ctx, operand) for operand in expr.operands]
            return and_(*parts) if expr.op is BoolOp.AND else or_(*parts)
        case NotExpr():
            return not_(await _expr(session, ctx, expr.operand))
        case _:
            return await _condition(session, ctx, expr)


async def _condition(session: AsyncSession, ctx: _Ctx, node: Condition) -> ColumnElement[bool]:
    if node.field.startswith(ISSUE_PREFIX):
        return await _delegated_issue_condition(session, ctx, node)
    try:
        field = WorklogField(node.field)
    except ValueError:
        raise unknown_field(
            node.field, node.field_position, [f.value for f in WorklogField] + [ISSUE_PREFIX]
        ) from None
    check_ops(node, WORKLOG_OPS[field])
    return _COMPILERS[field](ctx, node)


# --- the delegation -----------------------------------------------------------


async def _delegated_issue_condition(
    session: AsyncSession, ctx: _Ctx, node: Condition
) -> ColumnElement[bool]:
    """`issue.<field> <op> <value>` — compiled by the ITEM dialect, correlated
    through `worklog.item_id`. The item compiler owns validation too, so an
    unknown `issue.` field reports the item dialect's own error (with the
    position rebased onto this query so the caret still lands correctly)."""
    inner = _rebase(node, node.field[len(ISSUE_PREFIX) :])
    try:
        compiled = await compile_item_query(
            session,
            Query(where=inner, order=()),
            definitions_by_key={},
            current_user_id=ctx.current_user_id,
        )
    except SlqError as error:
        # Re-raise with the caret on the OUTER field: the delegated AST carries
        # the rewritten (prefix-stripped) name, so the item dialect's position
        # would point a few characters left of what the user actually typed.
        raise SlqError(str(error), node.field_position) from None
    if compiled.where is None:
        raise SlqError(f"unknown field '{node.field}'", node.field_position)
    matching = select(WorkItem.id).where(compiled.where)
    # Negation is already inside the delegated clause (the item compiler applies
    # it), so this wrapper must NOT negate again — an item that fails the inner
    # test simply is not in the id set.
    return Worklog.item_id.in_(matching)


def _rebase(node: Condition, field: str) -> Condition:
    """The same condition, re-pointed at the item field it delegates to."""
    match node:
        case Comparison():
            return Comparison(field, node.op, node.value, node.field_position, node.op_position)
        case Membership():
            return Membership(field, node.values, node.negated, node.field_position)
        case EmptyCheck():
            return EmptyCheck(field, node.negated, node.field_position)
    raise SlqError(f"unsupported condition for '{node.field}'", node.field_position)


# --- worklog's own fields ------------------------------------------------------


def _issue(ctx: _Ctx, node: Condition) -> ColumnElement[bool]:
    """Bare `issue`: EMPTY (general worklogs, spec 59) or a specific key."""
    if isinstance(node, EmptyCheck):
        clause = Worklog.item_id.is_(None)
        return not_(clause) if node.negated else clause
    keys = [plain(value, node.field).upper() for value in values_of(node)]
    matching = select(WorkItem.id).join(Project, Project.id == WorkItem.project_id)
    conditions = []
    for key in keys:
        project_key, _, number = key.rpartition("-")
        if not project_key or not number.isdigit():
            raise SlqError(f"'{key}' is not an issue key", node.field_position)
        conditions.append(and_(Project.key == project_key, WorkItem.number == int(number)))
    return polarity(node, Worklog.item_id.in_(matching.where(or_(*conditions))))


def _project(ctx: _Ctx, node: Condition) -> ColumnElement[bool]:
    """A worklog's OWN project column — set for item-linked rows and for
    project-anchored general ones, NULL for category-only entries."""
    if isinstance(node, EmptyCheck):
        clause = Worklog.project_id.is_(None)
        return not_(clause) if node.negated else clause
    keys = [plain(value, node.field).upper() for value in values_of(node)]
    matching = select(Project.id).where(Project.key.in_(keys))
    return polarity(node, Worklog.project_id.in_(matching))


def _author(ctx: _Ctx, node: Condition) -> ColumnElement[bool]:
    """`me` or a person by email/name — the builtin people-field language, so
    the two dialects don't teach two conventions."""
    conditions: list[ColumnElement[bool]] = []
    texts: list[str] = []
    for value in values_of(node):
        if is_sentinel(value, ME_LITERAL):
            conditions.append(Worklog.author_id == ctx.current_user_id)
        else:
            texts.append(value.text)
    if texts:
        people = select(User.id).where(
            or_(*[User.email.ilike(text) for text in texts], *[User.name.ilike(text) for text in texts])
        )
        conditions.append(Worklog.author_id.in_(people))
    return polarity(node, or_(*conditions))


def _category(ctx: _Ctx, node: Condition) -> ColumnElement[bool]:
    if isinstance(node, EmptyCheck):
        clause = Worklog.category_id.is_(None)
        return not_(clause) if node.negated else clause
    names = [plain(value, node.field) for value in values_of(node)]
    matching = select(WorkCategory.id).where(
        or_(*[WorkCategory.name.ilike(name) for name in names])
    )
    return polarity(node, Worklog.category_id.in_(matching))


def _worked_on(ctx: _Ctx, node: Condition) -> ColumnElement[bool]:
    if not isinstance(node, Comparison):
        raise SlqError("'worked_on' takes a single date", node.field_position)
    return polarity(node, compare(Worklog.worked_on, node.op, date_value(node.value, node.field)))


def _time(ctx: _Ctx, node: Condition) -> ColumnElement[bool]:
    """Duration literals in the SAME language the log-work form accepts (`90m`,
    `1h30m`, `2d`) — resolved with the instance's hours-per-day so `1d` means
    what the timesheet means by a day."""
    if not isinstance(node, Comparison):
        raise SlqError("'time' takes a single duration", node.field_position)
    try:
        seconds = parse_duration(
            node.value.text, hours_per_day=ctx.hours_per_day, days_per_week=ctx.days_per_week
        )
    except DurationError as error:
        raise SlqError(str(error), node.value.position) from None
    return polarity(node, compare(Worklog.time_spent_seconds, node.op, seconds))


def _note(ctx: _Ctx, node: Condition) -> ColumnElement[bool]:
    if not isinstance(node, Comparison):
        raise SlqError("'note' takes a single value", node.field_position)
    text = plain(node.value, node.field)
    clause = (
        Worklog.note.ilike(f"%{escape_like(text)}%")
        if node.op is CompareOp.CONTAINS
        else Worklog.note == text
    )
    return not_(clause) if negated(node) else clause


_COMPILERS = {
    WorklogField.ISSUE: _issue,
    WorklogField.PROJECT: _project,
    WorklogField.AUTHOR: _author,
    WorklogField.CATEGORY: _category,
    WorklogField.WORKED_ON: _worked_on,
    WorklogField.TIME: _time,
    WorklogField.NOTE: _note,
}


def worklog_field_names() -> list[str]:
    """Field names for autocomplete — worklog's own, plus the `issue.` prefix
    whose completions the suggest layer delegates to the item dialect."""
    return [f.value for f in WorklogField]


__all__ = [
    "CompiledWorklogQuery",
    "compile_worklog_query",
    "worklog_field_names",
]
