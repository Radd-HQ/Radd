"""The read pipeline: hydrate → emit → permission-filtered ItemRead."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from ..changes import diff_item_reads, field_name_map
from ..enums import ItemEntity, ItemEvent
from ..hydration import hydrate
from ..models import WorkItem
from ..schemas import ItemRead
from .queries import _alias_item, _parse_key, require_item
from .visibility import (
    attach_capabilities,
    ensure_item_relation,
    relation_read_clause,
    _builtin_read_denied,
    _field_ctx,
    _filter_read,
    _internal_visible,
)


async def _hydrate_one(
    session: AsyncSession,
    item: WorkItem,
    project: Project,
    actor: User,
    permissions: frozenset[Permission],
) -> ItemRead:
    """Hydrated read of one item — used for event payloads and for the
    pre-mutation 'before' snapshot the change diff compares against. Custom
    fields stay unfiltered (stream consumers are trusted), but cross-project
    refs inherit the ACTOR's readability (RADD-839): an event snapshot must not
    carry references its own author could never see. Before/after are filtered
    identically, so diffs stay consistent; automations/system writes run as an
    instance admin and lose nothing."""
    internal_visible = _internal_visible({project.id: permissions})
    readable_map = await authz.readable_projects(session, actor)
    return (
        await hydrate(
            session,
            [item],
            internal_visible=internal_visible,
            actor_id=actor.id,
            readable_project_ids=frozenset(readable_map),
            relation_clause=await relation_read_clause(session, actor, readable_map),
        )
    )[0]


async def _finish(
    session: AsyncSession,
    item: WorkItem,
    project: Project,
    event_type: ItemEvent,
    actor: User,
    ctx: fields.FieldAccessContext,
    definitions: Sequence[FieldDefinition],
    permissions: frozenset[Permission],
    *,
    before: ItemRead | None = None,
    occurred_at: datetime | None = None,
    event_actor_id: uuid.UUID | None = None,
) -> ItemRead:
    read = await _hydrate_one(session, item, project, actor, permissions)
    # Event payloads keep the FULL custom_fields — stream consumers are trusted
    # (docs/modules.md); only API responses are filtered per-actor.
    payload = read.model_dump(mode="json")
    # Field-level diff for the History tab / audit (and richer webhook/automation
    # signals). Computed from the pre-mutation snapshot; omitted on create.
    if before is not None:
        changes = diff_item_reads(before, read, field_names=field_name_map(definitions))
        if changes:
            payload["changes"] = changes
    await events.emit(
        session,
        event_type=event_type,
        entity_type=ItemEntity.ITEM,
        entity_id=item.id,
        actor_id=event_actor_id or actor.id,  # import: credit the original reporter
        payload=payload,
        occurred_at=occurred_at,
    )
    builtin_denied = await _builtin_read_denied(session, project, ctx)
    return _filter_read(read, definitions, ctx, builtin_denied)


async def get_item(session: AsyncSession, item_id: uuid.UUID, actor: User) -> ItemRead:
    item = await require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    permissions = await authz.require(session, actor, Permission.ITEM_READ, project=project)
    await ensure_item_relation(
        session, actor, item, permissions, Permission.ITEM_READ, as_missing=True
    )
    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)
    internal_visible = _internal_visible({project.id: permissions})
    readable_map = await authz.readable_projects(session, actor)
    read = (
        await hydrate(
            session,
            [item],
            internal_visible=internal_visible,
            actor_id=actor.id,
            readable_project_ids=frozenset(readable_map),
            relation_clause=await relation_read_clause(session, actor, readable_map),
        )
    )[0]
    builtin_denied = await _builtin_read_denied(session, project, ctx)
    filtered = _filter_read(read, definitions, ctx, builtin_denied)
    # RADD-842: the per-row verdict on the detail read.
    return (
        await attach_capabilities(
            session, actor, [filtered], {item.id: item}, {project.id: permissions}
        )
    )[0]


async def get_item_by_key(session: AsyncSession, key: str, actor: User) -> ItemRead:
    """Resolve an item by its canonical display key (`TD-1234`). Numbering is
    per-project; project keys are globally unique, so the resolution is
    unambiguous."""
    parsed = _parse_key(key)
    if parsed is None:
        raise NotFoundError(ItemEntity.ITEM, key)
    project_key, number = parsed
    result = await session.execute(
        select(WorkItem.id, Project)
        .join(Project, Project.id == WorkItem.project_id)
        .where(Project.key == project_key.upper(), WorkItem.number == number)
    )
    for item_id, project in result.all():
        try:
            await authz.require(session, actor, Permission.ITEM_READ, project=project)
        except ForbiddenError:
            continue
        return await get_item(session, item_id, actor)
    # Key-alias fallback (spec 68): a moved item keeps resolving under its old
    # key — the response carries its CURRENT key, so clients converge on it.
    aliased = await _alias_item(session, key)
    if aliased is not None:
        return await get_item(session, aliased.id, actor)
    raise NotFoundError(ItemEntity.ITEM, key)
