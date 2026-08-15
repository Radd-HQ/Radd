"""Clone an item (RADD-1088) — the most-used shortcut the tracker lacked.

Built THROUGH `create_item`, so every creation check applies unchanged. The
copy can't smuggle anything: the source is read with the ACTOR's eyes (custom
fields they can't read are already filtered, restricted builtins blanked),
and on top of that anything the actor can't WRITE here is dropped — cloning
must never be the door around a field grant.

Copied: title (caller's, or "Copy of …"), description, kind, type, priority,
labels, dates, estimate, custom fields, parent (an issue clone stays under
its epic; a subtask clone under its issue). Never copied: comments, worklogs,
history, watchers, assignee/reporter (a clone is fresh work, not a forged
trail — the cloner becomes the reporter), state (clones land in the initial
state), flags/stars. The clone links back to the original with `relates`.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.fields import service as fields
from radd.modules.projects import service as projects_service

from ..enums import ItemKind
from ..models import ItemLink, WorkItem
from ..schemas import ItemCreate, ItemRead
from .core import create_item
from .queries import require_item
from .read import get_item
from .visibility import _field_ctx

CLONE_LINK_TYPE = "relates"
CLONE_TITLE_PREFIX = "Copy of "
_TITLE_MAX = 500
#: Builtins a clone writes that CAN carry a write rule (spec 36) — checked so a
#: restricted one drops instead of 403ing the whole clone.
_CLONE_BUILTINS = ("description", "labels", "start_date", "target_date", "estimate_points")


async def clone_item(
    session: AsyncSession,
    item_id: uuid.UUID,
    actor: User,
    *,
    title: str | None = None,
    include_subtasks: bool = False,
) -> ItemRead:
    source = await get_item(session, item_id, actor)  # actor-filtered read
    project = await projects_service.get_project(session, source.project_id)
    permissions = await authz.require(session, actor, Permission.ITEM_CREATE, project=project)
    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)

    by_key = {d.key: d for d in definitions}
    custom_fields = {
        key: value
        for key, value in source.custom_fields.items()
        if key in by_key and fields.field_writable(by_key[key], ctx)
    }
    denied = set(
        fields.builtin_write_denied(
            _CLONE_BUILTINS, ctx.builtin_grants, ctx.as_subject(), ctx.project_id
        )
    )

    payload = ItemCreate(
        project_id=source.project_id,
        title=(title or f"{CLONE_TITLE_PREFIX}{source.title}")[:_TITLE_MAX],
        description="" if "description" in denied else source.description,
        kind=source.kind,
        type_id=source.type.id if source.type else None,
        parent_id=source.parent.id if source.parent else None,
        priority=source.priority,
        labels=[] if "labels" in denied else list(source.labels),
        start_date=None if "start_date" in denied else source.start_date,
        target_date=None if "target_date" in denied else source.target_date,
        estimate_points=None if "estimate_points" in denied else source.estimate_points,
        custom_fields=custom_fields,
    )
    created = await create_item(session, payload, actor)

    # The provenance link, inserted directly: `relates` is a built-in symmetric
    # manual type with no rules to trip, both ends are the same project, and the
    # cloner already proved ITEM_CREATE — routing through add_item_link would
    # additionally demand ITEM_UPDATE and could strand a created-but-unlinked
    # clone behind a 403.
    session.add(
        ItemLink(
            source_item_id=created.id, target_item_id=source.id, link_type=CLONE_LINK_TYPE
        )
    )
    await session.flush()

    if include_subtasks and source.kind is not ItemKind.SUBTASK:
        children = (
            await session.execute(
                select(WorkItem)
                .where(
                    WorkItem.parent_id == source.id,
                    WorkItem.kind == ItemKind.SUBTASK.value,
                    WorkItem.archived_at.is_(None),
                )
                .order_by(WorkItem.number)
            )
        ).scalars()
        for child in children:
            child_read = await get_item(session, child.id, actor)
            await create_item(
                session,
                ItemCreate(
                    project_id=source.project_id,
                    title=child_read.title,
                    description=child_read.description,
                    kind=ItemKind.SUBTASK,
                    type_id=child_read.type.id if child_read.type else None,
                    parent_id=created.id,
                    priority=child_read.priority,
                    labels=list(child_read.labels),
                    estimate_points=child_read.estimate_points,
                    custom_fields={
                        key: value
                        for key, value in child_read.custom_fields.items()
                        if key in by_key and fields.field_writable(by_key[key], ctx)
                    },
                ),
                actor,
            )

    # Re-read so the returned clone carries the link and the subtask rollup.
    fresh = await require_item(session, created.id)
    return await get_item(session, fresh.id, actor)
