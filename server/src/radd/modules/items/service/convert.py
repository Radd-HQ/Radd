"""Convert an item's kind (RADD-1089) — epic ↔ issue ↔ subtask, explicitly.

`kind` stays create-only on every other surface on purpose: a conversion is a
structural claim about the hierarchy (epic ← issue ← subtask), so each
direction either satisfies that shape or refuses with a reason NAMING what
blocks it — the child issues to re-parent, the subtasks to promote, the
parent issue a subtask needs. The one automatic adjustment is DETACHING an
incompatible parent (subtask→issue leaves its old parent issue; anything→epic
leaves any parent), and that is never silent: the parent change lands in the
same `changes` list as the kind change, so history shows exactly what moved.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.fields import service as fields
from radd.modules.projects import service as projects_service

from ..changes import diff_item_reads, field_name_map
from ..enums import ItemEntity, ItemEvent, ItemKind
from ..models import WorkItem
from ..schemas import ItemRead
from .queries import require_item
from .read import _hydrate_one
from .relations import _resolve_parent
from .visibility import _builtin_read_denied, _field_ctx, _filter_read, ensure_item_relation

_UNSET = object()


async def convert_item_kind(
    session: AsyncSession,
    item_id: uuid.UUID,
    actor: User,
    *,
    kind: ItemKind,
    parent_id: uuid.UUID | None | object = _UNSET,
) -> ItemRead:
    item = await require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    permissions = await authz.require(session, actor, Permission.ITEM_UPDATE, project=project)
    await ensure_item_relation(session, actor, item, permissions, Permission.ITEM_UPDATE)

    old_kind = ItemKind(item.kind)
    if old_kind == kind and parent_id is _UNSET:
        raise ConflictError(ItemEntity.ITEM, reason=f"item is already a {kind.value}")

    child_count = (
        await session.scalar(
            select(func.count()).select_from(WorkItem).where(WorkItem.parent_id == item.id)
        )
    ) or 0
    if kind == ItemKind.EPIC and child_count:
        raise ConflictError(
            ItemEntity.ITEM,
            reason=f"an epic's children are issues — convert or re-parent this item's "
            f"{child_count} subtask(s) first",
        )
    if kind == ItemKind.ISSUE and old_kind == ItemKind.EPIC and child_count:
        raise ConflictError(
            ItemEntity.ITEM,
            reason=f"re-parent this epic's {child_count} child issue(s) first",
        )
    if kind == ItemKind.SUBTASK and child_count:
        raise ConflictError(
            ItemEntity.ITEM,
            reason=f"a subtask cannot have children — this item has {child_count}",
        )

    # Resolve the parent for the NEW kind: an explicit id is validated against
    # the hierarchy; omitted means keep-when-compatible, detach otherwise.
    if parent_id is _UNSET:
        keep = item.parent_id
        if kind == ItemKind.EPIC:
            keep = None  # epics have no parent
        elif keep is not None:
            current_parent = await require_item(session, keep)
            required = ItemKind.EPIC if kind == ItemKind.ISSUE else ItemKind.ISSUE
            if ItemKind(current_parent.kind) != required:
                keep = None  # incompatible — detach, recorded in `changes`
        new_parent_id: uuid.UUID | None = keep
    else:
        new_parent_id = parent_id  # type: ignore[assignment]
    await _resolve_parent(session, kind, new_parent_id)

    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)
    before = await _hydrate_one(session, item, project, actor, permissions)

    item.kind = kind.value
    item.parent_id = new_parent_id
    await session.flush()

    after = await _hydrate_one(session, item, project, actor, permissions)
    changes = diff_item_reads(before, after, field_names=field_name_map(definitions))
    # diff_item_reads deliberately doesn't know `kind` (it never changes
    # elsewhere) — the conversion IS the event, so it leads the list.
    changes.insert(0, {"field": "kind", "from": old_kind.value, "to": kind.value})
    await events.emit(
        session,
        event_type=ItemEvent.UPDATED,
        entity_type=ItemEntity.ITEM,
        entity_id=item.id,
        actor_id=actor.id,
        payload={
            "item": {
                **after.model_dump(mode="json"),
                "project": {"id": str(project.id), "key": project.key, "name": project.name},
            },
        },
        changes=changes,
    )
    builtin_denied = await _builtin_read_denied(session, project, ctx)
    return _filter_read(after, definitions, ctx, builtin_denied)
