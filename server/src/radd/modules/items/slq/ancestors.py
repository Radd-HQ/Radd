"""Ancestor fields (spec 83): bare `epic`/`parent` + `epic.*`/`parent.*`.

`parent` targets the DIRECT parent (WorkItem.parent_id) and is strictly
relative — an item is never its own parent. `epic` names a CONTAINER instead,
the epic an item belongs to, and an epic belongs to ITSELF (spec 83 amendment,
2026-07-27): one aliased self-join chain I (item) / P (parent) / G
(grandparent) per condition, correlated on the outer row, deriving
`hierarchy.nearest_epic_case` as a scalar subquery. So `epic = TD-3` and
`epic.state != Done` return the epic alongside the work it governs, and
`epic IS EMPTY` means work no epic governs (a parentless issue and its
subtasks) — epics no longer land in that bucket.

Sub-field conditions (`.state` / `.category` / `.assignee` / `.priority`)
mirror the item-level value semantics (state matching adds case-insensitivity
per the spec) and compile to `<ancestor id> IN (SELECT id FROM work_items
WHERE <predicate>)` — correlated comparisons, never joins, so they stay
correct under OR/NOT with the usual SQL NULL rule: `!=`/`NOT IN` don't match
items without the ancestor. Bare keys resolve at COMPILE time through the
spec-68 alias-aware resolver (`compile_query` pre-pass -> Context); an
unknown key is a positioned SlqError (-> 422). Filter-only: none of these
fields are sortable (catalog), so ORDER BY rejects them like other
unsupported sorts.
"""

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from radd.modules.workflow.models import State
from radd.modules.workflow.types import StateCategory

from ..enums import Priority
from ..filters import NONE_LITERAL
from ..hierarchy import nearest_epic_case
from ..models import WorkItem
from .builtins import user_match
from .catalog import SlqField
from .errors import SlqError
from .helpers import (
    ITEM_KEY_RE,
    Context,
    enum_values,
    is_sentinel,
    item_key,
    plain,
    polarity,
    values_of,
)
from .parser import BoolExpr, Comparison, Condition, EmptyCheck, Expr, Membership, NotExpr

_BARE_FIELDS = frozenset({SlqField.EPIC.value, SlqField.PARENT.value})


# --- compile-time key resolution (the compile_query pre-pass) ---


def ancestor_key_texts(expr: Expr | None) -> set[str]:
    """Uppercased bare `epic`/`parent` key values in the WHERE tree. Only
    well-formed keys are collected — malformed values and sentinels fail (or
    compile) in place with their own position during the pure compile step."""
    match expr:
        case Comparison() | Membership() if expr.field in _BARE_FIELDS:
            return {
                value.text.upper()
                for value in values_of(expr)
                if not is_sentinel(value, NONE_LITERAL) and ITEM_KEY_RE.match(value.text)
            }
        case NotExpr():
            return ancestor_key_texts(expr.operand)
        case BoolExpr():
            return set().union(*(ancestor_key_texts(operand) for operand in expr.operands))
    return set()


async def resolve_ancestor_keys(
    session: AsyncSession, texts: set[str]
) -> dict[str, uuid.UUID]:
    """key -> item id via the spec-68 alias-aware resolver (`find_item_by_key`);
    keys that resolve nowhere are omitted, and the compile step turns the miss
    into a positioned SlqError."""
    if not texts:
        return {}
    # Lazy import: the items service itself imports this package.
    from radd.modules.items import service as items_service

    resolved: dict[str, uuid.UUID] = {}
    for text in sorted(texts):
        item = await items_service.find_item_by_key(session, text)
        if item is not None:
            resolved[text] = item.id
    return resolved


# --- the ancestor id a condition tests ---


def _epic_id() -> ColumnElement[uuid.UUID | None]:
    """Correlated scalar subquery: the id of the epic the outer WorkItem row
    belongs to — ITSELF when it is an epic, else the nearest epic ancestor
    (NULL when there is none), per `hierarchy.nearest_epic_case`.

    Correlating on the ITEM (not on its parent) and outer-joining upwards is
    what lets a parentless epic still produce a row and hit the self arm."""
    item = aliased(WorkItem)
    parent = aliased(WorkItem)
    grandparent = aliased(WorkItem)
    return (
        select(nearest_epic_case(item, parent, grandparent))
        .select_from(item)
        .outerjoin(parent, parent.id == item.parent_id)
        .outerjoin(grandparent, grandparent.id == parent.parent_id)
        .where(item.id == WorkItem.id)
        .scalar_subquery()
    )


def _target(*, epic: bool) -> ColumnElement:
    return _epic_id() if epic else WorkItem.parent_id


# --- bare epic/parent: = key | != key | IN (key, none) | IS [NOT] EMPTY ---


def _bare(ctx: Context, node: Condition, *, epic: bool) -> ColumnElement[bool]:
    target = _target(epic=epic)
    if isinstance(node, EmptyCheck):
        return polarity(node, target.is_(None))
    ids: list[uuid.UUID] = []
    conditions: list[ColumnElement[bool]] = []
    for value in values_of(node):
        if is_sentinel(value, NONE_LITERAL):
            conditions.append(target.is_(None))
            continue
        item_key(value, node.field)  # shape + sentinel check, positioned
        resolved = ctx.ancestor_ids_by_key.get(value.text.upper())
        if resolved is None:
            raise SlqError(f"unknown item '{value.text}'", value.position)
        ids.append(resolved)
    if ids:
        conditions.append(target.in_(ids))
    return polarity(node, or_(*conditions))


# --- sub-fields: a predicate over the ancestor row, correlated through its id ---

_Predicate = Callable[[Context, Condition, Any], ColumnElement[bool]]


def _state_predicate(ctx: Context, node: Condition, ancestor) -> ColumnElement[bool]:
    names = [plain(value, node.field).lower() for value in values_of(node)]
    return ancestor.state_id.in_(select(State.id).where(func.lower(State.name).in_(names)))


def _category_predicate(ctx: Context, node: Condition, ancestor) -> ColumnElement[bool]:
    categories = [c.value for c in enum_values(node, StateCategory)]
    return ancestor.state_id.in_(select(State.id).where(State.category.in_(categories)))


def _assignee_predicate(ctx: Context, node: Condition, ancestor) -> ColumnElement[bool]:
    if isinstance(node, EmptyCheck):
        return ancestor.assignee_id.is_(None)
    return user_match(ctx, node, ancestor.assignee_id)


def _priority_predicate(ctx: Context, node: Condition, ancestor) -> ColumnElement[bool]:
    return ancestor.priority.in_([p.value for p in enum_values(node, Priority)])


def _sub_condition(
    ctx: Context, node: Condition, *, epic: bool, predicate: _Predicate
) -> ColumnElement[bool]:
    ancestor = aliased(WorkItem)
    matching = select(ancestor.id).where(predicate(ctx, node, ancestor))
    return polarity(node, _target(epic=epic).in_(matching))


def _compiler(*, epic: bool, predicate: _Predicate):
    return lambda ctx, node: _sub_condition(ctx, node, epic=epic, predicate=predicate)


ANCESTOR_COMPILERS = {
    SlqField.EPIC: lambda ctx, node: _bare(ctx, node, epic=True),
    SlqField.PARENT: lambda ctx, node: _bare(ctx, node, epic=False),
    SlqField.EPIC_STATE: _compiler(epic=True, predicate=_state_predicate),
    SlqField.EPIC_CATEGORY: _compiler(epic=True, predicate=_category_predicate),
    SlqField.EPIC_ASSIGNEE: _compiler(epic=True, predicate=_assignee_predicate),
    SlqField.EPIC_PRIORITY: _compiler(epic=True, predicate=_priority_predicate),
    SlqField.PARENT_STATE: _compiler(epic=False, predicate=_state_predicate),
    SlqField.PARENT_CATEGORY: _compiler(epic=False, predicate=_category_predicate),
    SlqField.PARENT_ASSIGNEE: _compiler(epic=False, predicate=_assignee_predicate),
    SlqField.PARENT_PRIORITY: _compiler(epic=False, predicate=_priority_predicate),
}
