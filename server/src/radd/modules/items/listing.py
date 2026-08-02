"""Builds the filtered `GET /items` query from `ItemListFilters` (spec 08).

Values repeated within one param are OR-ed; different params are AND-ed.
`cf` equality/containment uses JSONB `@>` — sequential-scan for now; expression
GIN indexes come later via the field registry's `indexed` flag (docs/modules.md).
"""

import uuid

from sqlalchemy import ColumnElement, Select, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.labels import service as labels_service
from radd.modules.workflow import service as workflow
from radd.modules.projects.models import Project

from .filters import IdOrNoneFilter, ItemFilterParam, ItemListFilters, parse_cf, parse_id_or_none
from .models import ItemLabel, WorkItem


def _id_or_none_clause(
    column: InstrumentedAttribute[uuid.UUID | None], parsed: IdOrNoneFilter
) -> ColumnElement[bool]:
    conditions: list[ColumnElement[bool]] = []
    if parsed.ids:
        conditions.append(column.in_(parsed.ids))
    if parsed.include_none:
        conditions.append(column.is_(None))
    return or_(*conditions)


async def _label_clause(
    session: AsyncSession, project_id: uuid.UUID | None, names: tuple[str, ...]
) -> ColumnElement[bool]:
    """Items carrying ANY of the given label names.

    Names resolve via the labels service over the distinct label ids in use
    (item_labels is items-owned; the labels table stays private to its module).
    """
    in_use = select(ItemLabel.label_id).distinct()
    if project_id:
        in_use = in_use.join(WorkItem, WorkItem.id == ItemLabel.item_id).where(
            WorkItem.project_id == project_id
        )
    used_ids = set((await session.execute(in_use)).scalars())
    by_id = await labels_service.labels_by_ids(session, used_ids)
    wanted_names = set(names)
    wanted = {label_id for label_id, label in by_id.items() if label.name in wanted_names}
    if not wanted:
        return false()  # none of the names is in use anywhere -> empty result
    return WorkItem.id.in_(select(ItemLabel.item_id).where(ItemLabel.label_id.in_(wanted)))


async def cf_definitions(
    session: AsyncSession, project: Project | None
) -> dict[str, FieldDefinition]:
    """key -> definition map for cf coercion and SLQ typing; instance-wide when
    cross-project (oldest definition wins —
    docs/modules.md)."""
    definitions = (
        await fields.definitions_for_project(session, project)
        if project is not None
        else await fields.list_fields(session)
    )
    by_key: dict[str, FieldDefinition] = {}
    for definition in definitions:
        by_key.setdefault(definition.key, definition)
    return by_key


async def apply_filters(
    session: AsyncSession,
    query: Select[tuple[WorkItem]],
    filters: ItemListFilters,
    project: Project | None,
) -> Select[tuple[WorkItem]]:
    """AND every present filter onto the listing query."""
    # Spec 38: archived items are hidden by default; archived=true shows ONLY them.
    query = query.where(
        WorkItem.archived_at.is_not(None) if filters.archived else WorkItem.archived_at.is_(None)
    )
    if filters.project_id:
        query = query.where(WorkItem.project_id == filters.project_id)
    if filters.state_ids:
        query = query.where(WorkItem.state_id.in_(filters.state_ids))
    if filters.categories:
        state_ids: set[uuid.UUID] = set()
        for category in set(filters.categories):
            state_ids.update(
                await workflow.state_ids_in_category(session, filters.project_id, category)
            )
        query = query.where(WorkItem.state_id.in_(state_ids))
    if filters.kinds:
        query = query.where(WorkItem.kind.in_([kind.value for kind in filters.kinds]))
    if filters.priorities:
        query = query.where(
            WorkItem.priority.in_([priority.value for priority in filters.priorities])
        )
    if filters.parent_id:
        query = query.where(WorkItem.parent_id == filters.parent_id)
    assignees = parse_id_or_none(ItemFilterParam.ASSIGNEE_ID, filters.assignee_ids)
    if assignees:
        query = query.where(_id_or_none_clause(WorkItem.assignee_id, assignees))
    teams = parse_id_or_none(ItemFilterParam.TEAM_ID, filters.team_ids)
    if teams:
        query = query.where(_id_or_none_clause(WorkItem.team_id, teams))
    cycles = parse_id_or_none(ItemFilterParam.CYCLE_ID, filters.cycle_ids)
    if cycles:
        query = query.where(_id_or_none_clause(WorkItem.cycle_id, cycles))
    if filters.labels:
        query = query.where(await _label_clause(session, filters.project_id, filters.labels))
    if filters.cf:
        definitions_by_key = await cf_definitions(session, project)
        for condition in parse_cf(filters.cf, definitions_by_key):
            query = query.where(WorkItem.custom_fields.contains(condition.payload))
    return query
