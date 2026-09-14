"""SLQ AST -> SQLAlchemy over WorkItem.

Entry point (`compile_query`) + boolean dispatch. Builtin fields compile in
`builtins.py`, ancestor fields (spec 83) in `ancestors.py`, custom fields in
`custom.py`, ORDER BY in `ordering.py`; shared coercion/checks in `helpers.py`.
The session is touched only to resolve label names (their table stays private
to the labels module) and bare `epic`/`parent` item keys (alias-aware, spec
68); everything else is pure clause construction, so validation-only callers
(views) reuse this directly.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, and_, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import SlqFieldContext, registries
from radd.modules.fields.models import FieldDefinition
from radd.modules.labels import service as labels_service

from ..models import ItemLabel, WorkItem
from .ancestors import ANCESTOR_COMPILERS, ancestor_key_texts, resolve_ancestor_keys
from .builtins import BUILTIN_COMPILERS
from .catalog import BUILTIN_OPS, SlqField
from .custom import custom_condition
from .errors import SlqError
from .catalog import ME_LITERAL
from .helpers import Context, check_ops, is_sentinel, plain, polarity
from .lexer import CompareOp
from .ordering import order_clause, order_joins
from .parser import BoolExpr, BoolOp, Comparison, Condition, Expr, Membership, NotExpr, Query


@dataclass(frozen=True)
class CompiledQuery:
    where: ColumnElement[bool] | None
    order: tuple[ColumnElement[Any], ...]
    #: RADD-1176: (target, on-clause) pairs the ORDER BY reaches through — the
    #: `states` row for `state`/`category`. A statement builder applies them
    #: with `.join(target, onclause)` before ordering; nothing else sees them.
    joins: tuple[tuple[Any, Any], ...] = ()


async def compile_query(
    session: AsyncSession,
    query: Query,
    *,
    definitions_by_key: Mapping[str, FieldDefinition],
    current_user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    denied_fields: frozenset[str] = frozenset(),
) -> CompiledQuery:
    """Compile a parsed query. `session`/`project_id` are only used to resolve
    label names (scoped to the project's labels-in-use when given) and bare
    `epic`/`parent` item keys (spec 83, alias-aware). `denied_fields` (RADD-840)
    carries the actor's read-restricted field names — conditions and sorts on
    them refuse at compile time, closing the bisection oracle."""
    labels = await _resolve_label_ids(session, project_id, _label_names(query.where))
    ancestors = await resolve_ancestor_keys(session, ancestor_key_texts(query.where))
    ctx = Context(definitions_by_key, current_user_id, labels, ancestors, denied_fields)
    where = _expr(ctx, query.where) if query.where is not None else None
    order = tuple(column for term in query.order for column in order_clause(ctx, term))
    return CompiledQuery(where=where, order=order, joins=order_joins(query.order))


def _expr(ctx: Context, expr: Expr) -> ColumnElement[bool]:
    match expr:
        case BoolExpr():
            combine = and_ if expr.op is BoolOp.AND else or_
            return combine(*(_expr(ctx, operand) for operand in expr.operands))
        case NotExpr():
            return not_(_expr(ctx, expr.operand))
    return _condition(ctx, expr)


# One dispatch table: item-level builtins + the spec-83 ancestor fields.
_CONDITION_COMPILERS = {**BUILTIN_COMPILERS, **ANCESTOR_COMPILERS}


def _condition(ctx: Context, node: Condition) -> ColumnElement[bool]:
    if node.field in ctx.denied_fields:
        # RADD-840: a filter on a field the actor can't read is a value oracle.
        raise SlqError(
            f"field '{node.field}' is read-restricted for you", node.field_position
        )
    try:
        builtin = SlqField(node.field)
    except ValueError:
        # Not a builtin — a plugin-registered SLQ field (e.g. `note`), else a custom field.
        spec = registries.slq_fields.get(node.field)
        if spec is not None:
            return _plugin_condition(ctx, node, spec)
        return custom_condition(ctx, node)
    check_ops(node, BUILTIN_OPS[builtin])
    return _CONDITION_COMPILERS[builtin](ctx, node)


def _plugin_condition(ctx: Context, node: Condition, spec: Any) -> ColumnElement[bool]:
    """Compile a plugin SLQ field (spec 94). The plugin's `item_ids(contains, value)` returns a
    Select of matching work-item ids; we wrap it as `work_item.id IN (…)` and apply negation. Only
    `=`, `!=`, `~` are supported for plugin fields."""
    if not isinstance(node, Comparison):
        raise SlqError(f"field '{node.field}' supports only = / != / ~", node.field_position)
    if node.op not in (CompareOp.EQ, CompareOp.NE, CompareOp.CONTAINS):
        raise SlqError(
            f"operator '{node.op.value}' is not valid for field '{node.field}'", node.op_position
        )
    contains = node.op is CompareOp.CONTAINS
    # `me` never reaches the resolver as text: plain() rejects the sentinel by
    # design, so branch on it here and hand the resolver a typed flag.
    is_me = is_sentinel(node.value, ME_LITERAL)
    matching_ids = spec.item_ids(
        contains,
        "" if is_me else plain(node.value, node.field),
        SlqFieldContext(current_user_id=ctx.current_user_id, is_me=is_me),
    )
    return polarity(node, WorkItem.id.in_(matching_ids))


# --- label name resolution (the one async step) ---


def _label_names(expr: Expr | None) -> set[str]:
    match expr:
        case Comparison(field=SlqField.LABEL.value):
            return {expr.value.text}
        case Membership(field=SlqField.LABEL.value):
            return {value.text for value in expr.values}
        case NotExpr():
            return _label_names(expr.operand)
        case BoolExpr():
            return set().union(*(_label_names(operand) for operand in expr.operands))
    return set()


async def _resolve_label_ids(
    session: AsyncSession, project_id: uuid.UUID | None, names: set[str]
) -> dict[str, tuple[uuid.UUID, ...]]:
    """name -> ids over the labels in use (same idiom as items/listing.py); a name
    used nowhere resolves to () and compiles to an empty match."""
    if not names:
        return {}
    in_use = select(ItemLabel.label_id).distinct()
    if project_id:
        in_use = in_use.join(WorkItem, WorkItem.id == ItemLabel.item_id).where(
            WorkItem.project_id == project_id
        )
    used_ids = set((await session.execute(in_use)).scalars())
    by_id = await labels_service.labels_by_ids(session, used_ids)
    resolved: dict[str, list[uuid.UUID]] = {name: [] for name in names}
    for label_id, label in by_id.items():
        if label.name in resolved:
            resolved[label.name].append(label_id)
    return {name: tuple(ids) for name, ids in resolved.items()}
