"""Compilers for the builtin SLQ fields (catalog.SlqField). Relations become
correlated IN/EXISTS subqueries — never joins — so they stay correct under OR
and NOT. Labels use the pre-resolved name->id map from the context.

Nullable to-one relations (assignee/reporter/team/type/cycle/release) pass
`polarity(..., nullable=True)`: their negative forms are the complement of
the positive ones, so `assignee != x` includes the unassigned (RADD-1139).
"""

from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, and_, false, not_, or_, select
from sqlalchemy.orm import aliased

from radd.modules.auth.models import User
from radd.modules.cycles import service as cycles_service
from radd.modules.cycles.types import CycleStatus
from radd.modules.itemtypes import service as itemtypes_service
from radd.modules.releases import service as releases_service
from radd.modules.teams.models import Team
from radd.modules.workflow.models import State
from radd.modules.workflow.types import StateCategory
from radd.modules.projects.models import Project

from ..enums import ItemKind, ItemLinkType, ItemVisibility, Priority
from ..filters import NONE_LITERAL
from ..models import ItemLabel, ItemLink, ItemStar, WorkItem
from .catalog import ME_LITERAL, SlqField
from .errors import SlqError
from .helpers import (
    LIKE_ESCAPE,
    Context,
    compare,
    date_value,
    enum_values,
    escape_like,
    int_value,
    is_sentinel,
    item_key,
    number_value,
    plain,
    polarity,
    values_of,
)
from .lexer import CompareOp
from .parser import Comparison, Condition, EmptyCheck, Membership


def _project(ctx: Context, node: Condition) -> ColumnElement[bool]:
    keys = [plain(v, node.field).upper() for v in values_of(node)]
    return polarity(node, WorkItem.project_id.in_(select(Project.id).where(Project.key.in_(keys))))


def _state(ctx: Context, node: Condition) -> ColumnElement[bool]:
    names = [plain(v, node.field) for v in values_of(node)]
    return polarity(node, WorkItem.state_id.in_(select(State.id).where(State.name.in_(names))))


def _category(ctx: Context, node: Condition) -> ColumnElement[bool]:
    categories = [c.value for c in enum_values(node, StateCategory)]
    subquery = select(State.id).where(State.category.in_(categories))
    return polarity(node, WorkItem.state_id.in_(subquery))


def _kind(ctx: Context, node: Condition) -> ColumnElement[bool]:
    return polarity(node, WorkItem.kind.in_([k.value for k in enum_values(node, ItemKind)]))


def _priority(ctx: Context, node: Condition) -> ColumnElement[bool]:
    return polarity(node, WorkItem.priority.in_([p.value for p in enum_values(node, Priority)]))


def user_match(
    ctx: Context, node: Comparison | Membership, column: ColumnElement
) -> ColumnElement[bool]:
    """The shared user-value language (`me` | `none` | email) over one user-FK
    column — assignee/reporter here, the spec-83 ancestor assignees too."""
    conditions: list[ColumnElement[bool]] = []
    emails: list[str] = []
    for value in values_of(node):
        if is_sentinel(value, NONE_LITERAL):
            conditions.append(column.is_(None))
        elif is_sentinel(value, ME_LITERAL):
            conditions.append(column == ctx.current_user_id)
        else:
            emails.append(value.text.lower())
    if emails:
        conditions.append(column.in_(select(User.id).where(User.email.in_(emails))))
    return or_(*conditions)


def _assignee(ctx: Context, node: Condition) -> ColumnElement[bool]:
    if isinstance(node, EmptyCheck):
        return polarity(node, WorkItem.assignee_id.is_(None))
    return polarity(node, user_match(ctx, node, WorkItem.assignee_id), nullable=True)


def _reporter(ctx: Context, node: Condition) -> ColumnElement[bool]:
    if isinstance(node, EmptyCheck):
        return polarity(node, WorkItem.reporter_id.is_(None))
    return polarity(node, user_match(ctx, node, WorkItem.reporter_id), nullable=True)


def _team(ctx: Context, node: Condition) -> ColumnElement[bool]:
    if isinstance(node, EmptyCheck):
        return polarity(node, WorkItem.team_id.is_(None))
    conditions: list[ColumnElement[bool]] = []
    names: list[str] = []
    for value in values_of(node):
        if is_sentinel(value, NONE_LITERAL):
            conditions.append(WorkItem.team_id.is_(None))
        else:
            names.append(plain(value, node.field))
    if names:
        conditions.append(WorkItem.team_id.in_(select(Team.id).where(Team.name.in_(names))))
    return polarity(node, or_(*conditions), nullable=True)


def _type(ctx: Context, node: Condition) -> ColumnElement[bool]:
    if isinstance(node, EmptyCheck):
        return polarity(node, WorkItem.type_id.is_(None))
    conditions: list[ColumnElement[bool]] = []
    names: list[str] = []
    for value in values_of(node):
        if is_sentinel(value, NONE_LITERAL):
            conditions.append(WorkItem.type_id.is_(None))
        else:
            names.append(plain(value, node.field))
    if names:
        conditions.append(WorkItem.type_id.in_(itemtypes_service.ids_by_names(names)))
    return polarity(node, or_(*conditions), nullable=True)


def _label(ctx: Context, node: Condition) -> ColumnElement[bool]:
    if isinstance(node, EmptyCheck):
        any_label = select(ItemLabel.item_id).where(ItemLabel.item_id == WorkItem.id).exists()
        return any_label if node.negated else not_(any_label)  # IS EMPTY = unlabeled
    ids = [
        label_id
        for value in values_of(node)
        for label_id in ctx.label_ids_by_name.get(plain(value, node.field), ())
    ]
    if not ids:
        return polarity(node, false())  # name in use nowhere
    has_label = (
        select(ItemLabel.item_id)
        .where(ItemLabel.item_id == WorkItem.id, ItemLabel.label_id.in_(ids))
        .exists()
    )
    return polarity(node, has_label)


def _title(ctx: Context, node: Condition) -> ColumnElement[bool]:
    assert isinstance(node, Comparison)  # ops table allows only = and ~
    text = plain(node.value, node.field)
    if node.op is CompareOp.CONTAINS:
        return WorkItem.title.ilike(f"%{escape_like(text)}%", escape=LIKE_ESCAPE)
    return WorkItem.title == text


def _key(ctx: Context, node: Condition) -> ColumnElement[bool]:
    clauses = []
    for value in values_of(node):
        project_key, number = item_key(value, node.field)
        clauses.append(
            and_(
                WorkItem.number == number,
                WorkItem.project_id.in_(select(Project.id).where(Project.key == project_key)),
            )
        )
    return polarity(node, or_(*clauses))


def _number(ctx: Context, node: Condition) -> ColumnElement[bool]:
    assert isinstance(node, Comparison)  # ops table: RANGE only, no IN/EMPTY
    return compare(WorkItem.number, node.op, int_value(node.value, node.field))


def _points(ctx: Context, node: Condition) -> ColumnElement[bool]:
    """Story points (spec 70): numeric comparisons + IS [NOT] EMPTY (= unestimated)."""
    if isinstance(node, EmptyCheck):
        return polarity(node, WorkItem.estimate_points.is_(None))
    assert isinstance(node, Comparison)  # ops table: RANGE, no IN
    return compare(WorkItem.estimate_points, node.op, number_value(node.value, node.field))


def _timestamp(column: ColumnElement[datetime], node: Condition) -> ColumnElement[bool]:
    """Whole-day semantics: = the day, > strictly after it, >= from its start, …"""
    assert isinstance(node, Comparison)
    day = datetime.combine(date_value(node.value, node.field), datetime.min.time())
    next_day = day + timedelta(days=1)
    match node.op:
        case CompareOp.EQ:
            return and_(column >= day, column < next_day)
        case CompareOp.NE:
            return or_(column < day, column >= next_day)
        case CompareOp.GT:
            return column >= next_day
        case CompareOp.GE:
            return column >= day
        case CompareOp.LT:
            return column < day
        case CompareOp.LE:
            return column < next_day
    raise TypeError(node.op)  # pragma: no cover


def _cycle(ctx: Context, node: Condition) -> ColumnElement[bool]:
    if isinstance(node, EmptyCheck):
        return polarity(node, WorkItem.cycle_id.is_(None))
    conditions: list[ColumnElement[bool]] = []
    names: list[str] = []
    for value in values_of(node):
        if is_sentinel(value, NONE_LITERAL):
            conditions.append(WorkItem.cycle_id.is_(None))
        else:
            names.append(plain(value, node.field))
    if names:
        conditions.append(WorkItem.cycle_id.in_(cycles_service.ids_by_names(names)))
    return polarity(node, or_(*conditions), nullable=True)


def _past_cycle(ctx: Context, node: Condition) -> ColumnElement[bool]:
    """Closed cycle stints (spec 56): cycles the item was in and LEFT — the
    carryover trail. The current cycle is `cycle`; `past_cycle IS NOT EMPTY`
    = "has rolled over at least once"."""
    closed = cycles_service.closed_stint_item_ids()
    if isinstance(node, EmptyCheck):
        return polarity(node, WorkItem.id.notin_(closed))
    conditions: list[ColumnElement[bool]] = []
    names: list[str] = []
    for value in values_of(node):
        if is_sentinel(value, NONE_LITERAL):
            conditions.append(WorkItem.id.notin_(closed))
        else:
            names.append(plain(value, node.field))
    if names:
        conditions.append(WorkItem.id.in_(cycles_service.closed_stint_item_ids(names)))
    return polarity(node, or_(*conditions))


def _release(ctx: Context, node: Condition) -> ColumnElement[bool]:
    if isinstance(node, EmptyCheck):
        return polarity(node, WorkItem.release_id.is_(None))
    conditions: list[ColumnElement[bool]] = []
    versions: list[str] = []
    for value in values_of(node):
        if is_sentinel(value, NONE_LITERAL):
            conditions.append(WorkItem.release_id.is_(None))
        else:
            versions.append(plain(value, node.field))
    if versions:
        conditions.append(WorkItem.release_id.in_(releases_service.ids_by_versions(versions)))
    return polarity(node, or_(*conditions), nullable=True)


def _block_link(*, incoming: bool, target_ids: ColumnElement | None = None) -> ColumnElement[bool]:
    """EXISTS a `blocks` link where this item is the source (outgoing) or target (incoming)."""
    this_side = ItemLink.target_item_id if incoming else ItemLink.source_item_id
    other_side = ItemLink.source_item_id if incoming else ItemLink.target_item_id
    conditions = [this_side == WorkItem.id, ItemLink.link_type == ItemLinkType.BLOCKS.value]
    if target_ids is not None:
        conditions.append(other_side.in_(target_ids))
    return select(ItemLink.id).where(*conditions).exists()


def _blocks_condition(node: Condition, *, incoming: bool) -> ColumnElement[bool]:
    if isinstance(node, EmptyCheck):
        exists = _block_link(incoming=incoming)
        return exists if node.negated else not_(exists)  # IS NOT EMPTY -> has link
    assert isinstance(node, Comparison)  # ops table: EQ only
    other = aliased(WorkItem)
    project_key, number = item_key(node.value, node.field)
    target_ids = select(other.id).where(
        other.number == number,
        other.project_id.in_(select(Project.id).where(Project.key == project_key)),
    )
    return _block_link(incoming=incoming, target_ids=target_ids)


def _date_field(column: ColumnElement, node: Condition) -> ColumnElement[bool]:
    """Plain Date column: direct comparison (no whole-day windowing) + IS [NOT] EMPTY."""
    if isinstance(node, EmptyCheck):
        return polarity(node, column.is_(None))
    assert isinstance(node, Comparison)
    return compare(column, node.op, date_value(node.value, node.field))


_BOOLEAN_WORDS = {"true": True, "false": False}


def _flagged(ctx: Context, node: Condition) -> ColumnElement[bool]:
    """First-class boolean flag (spec 24): `flagged = true` / `flagged = false`."""
    assert isinstance(node, Comparison)  # ops table: EQUALITY only, no EmptyCheck
    if node.value.text not in _BOOLEAN_WORDS:
        raise SlqError(
            f"field 'flagged' expects true or false, got '{node.value.text}'", node.value.position
        )
    return compare(WorkItem.flagged, node.op, _BOOLEAN_WORDS[node.value.text])


def _visibility(ctx: Context, node: Condition) -> ColumnElement[bool]:
    """Spec 121: `visibility = public|internal|restricted` (also != / IN)."""
    return polarity(
        node, WorkItem.visibility.in_([v.value for v in enum_values(node, ItemVisibility)])
    )


def _starred(ctx: Context, node: Condition) -> ColumnElement[bool]:
    """Personal star for the requesting user (spec 24): `starred = true|false`.
    An EXISTS over item_stars scoped to the current user."""
    assert isinstance(node, Comparison)  # ops table: EQUALITY only
    if node.value.text not in _BOOLEAN_WORDS:
        raise SlqError(
            f"field 'starred' expects true or false, got '{node.value.text}'", node.value.position
        )
    wanted = _BOOLEAN_WORDS[node.value.text]
    has_star = (
        select(ItemStar.item_id)
        .where(ItemStar.item_id == WorkItem.id, ItemStar.user_id == ctx.current_user_id)
        .exists()
    )
    # `= true` matches starred, `!= true` / `= false` matches the rest.
    return has_star if wanted == (node.op is CompareOp.EQ) else not_(has_star)


BUILTIN_COMPILERS = {
    SlqField.PROJECT: _project,
    SlqField.STATE: _state,
    SlqField.CATEGORY: _category,
    SlqField.KIND: _kind,
    SlqField.TYPE: _type,
    SlqField.PRIORITY: _priority,
    SlqField.ASSIGNEE: _assignee,
    SlqField.REPORTER: _reporter,
    SlqField.TEAM: _team,
    SlqField.LABEL: _label,
    SlqField.TITLE: _title,
    SlqField.KEY: _key,
    SlqField.NUMBER: _number,
    SlqField.CREATED: lambda ctx, node: _timestamp(WorkItem.created_at, node),
    SlqField.UPDATED: lambda ctx, node: _timestamp(WorkItem.updated_at, node),
    SlqField.CYCLE: _cycle,
    SlqField.CYCLE_STATUS: lambda ctx, node: polarity(
        node, WorkItem.cycle_id.in_(cycles_service.ids_by_status(
            [value.value for value in enum_values(node, CycleStatus)]
        )), nullable=True
    ),
    SlqField.PAST_CYCLE: _past_cycle,
    SlqField.RELEASE: _release,
    SlqField.FLAGGED: _flagged,
    SlqField.VISIBILITY: _visibility,
    SlqField.STARRED: _starred,
    SlqField.POINTS: _points,
    SlqField.BLOCKS: lambda ctx, node: _blocks_condition(node, incoming=False),
    SlqField.BLOCKED: lambda ctx, node: _blocks_condition(node, incoming=True),
    SlqField.START: lambda ctx, node: _date_field(WorkItem.start_date, node),
    SlqField.TARGET: lambda ctx, node: _date_field(WorkItem.target_date, node),
}
