"""Bulk operations: batch edit, cross-project move, id listing.

Every per-item change goes through the single-item service inside its own
SAVEPOINT, so RBAC, field rules, guards, events and realtime keep their exact
semantics and one bad item is skipped and reported, never failing the batch.
A move takes EXACTLY the selection (the hierarchy spans projects), re-keys it,
maps state/type by name and writes `item_key_aliases` so old URLs resolve.
"""

import logging
import uuid
from collections.abc import Sequence
from itertools import batched

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.fields import service as fields
from radd.modules.itemtypes import service as itemtypes
from radd.modules.workflow import service as workflow
from radd.modules.workflow.guards import TransitionError
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .changes import diff_item_reads, field_name_map
from .enums import BulkSkipReason, ItemEntity, ItemEvent
from .filters import ItemListFilters
from .hydration import label_names
from .models import ItemKeyAlias, WorkItem
from .schemas import (
    BulkMovedItem,
    BulkMoveResult,
    BulkSkipped,
    BulkUpdateResult,
    ItemBulkMove,
    ItemBulkPatch,
    ItemBulkUpdate,
    ItemIds,
    ItemUpdate,
)
from .service import set_archived, update_item
from .service.scope import visible_ids_query

# Package-private helpers — reached through their concern module, not the service
# barrel, which exports only the items module's public surface.
from .service.read import _hydrate_one, event_item
from .service.visibility import _check_builtin_field_rules, _field_ctx
from radd.modules.events import service as events

logger = logging.getLogger(__name__)

# ItemBulkPatch fields forwarded 1:1 into a per-item ItemUpdate (labels/archived
# are handled separately — deltas and a dedicated service call respectively).
_PASSTHROUGH_FIELDS = (
    "state_id",
    "assignee_id",
    "team_id",
    "priority",
    "type_id",
    "cycle_id",
    "release_id",
    "flagged",
)


def _skip(
    item_id: uuid.UUID, key: str | None, reason: BulkSkipReason, detail: str | None = None
) -> BulkSkipped:
    return BulkSkipped(item_id=item_id, key=key, reason=reason, detail=detail)


def _skip_for(
    exc: Exception,
    item_id: uuid.UUID,
    key: str | None,
    *,
    invalid_target: tuple[type[Exception], ...],
    operation: str,
) -> BulkSkipped:
    """Map one item's failure to its skip reason. `invalid_target` errors are a
    project-scoped value that doesn't apply to this item's project — expected when
    a selection spans projects. Call from inside the `except` (logs the traceback)."""
    if isinstance(exc, ForbiddenError):
        return _skip(item_id, key, BulkSkipReason.FORBIDDEN)
    if isinstance(exc, TransitionError):
        return _skip(item_id, key, BulkSkipReason.TRANSITION_BLOCKED, "; ".join(exc.errors))
    if isinstance(exc, invalid_target):
        return _skip(item_id, key, BulkSkipReason.INVALID_TARGET, str(exc))
    logger.exception("bulk-%s failed for item %s", operation, item_id)
    return _skip(item_id, key, BulkSkipReason.ERROR)


async def _item_key(session: AsyncSession, item: WorkItem) -> str:
    keys = await projects_service.project_keys(session, [item.project_id])
    return f"{keys[item.project_id]}-{item.number}"


async def _apply_one(
    session: AsyncSession, item: WorkItem, patch: ItemBulkPatch, actor: User
) -> None:
    """Apply the bulk patch to ONE item via the ordinary service calls."""
    kwargs: dict = {}
    for field in _PASSTHROUGH_FIELDS:
        if field in patch.model_fields_set:
            kwargs[field] = getattr(patch, field)
    if patch.add_labels is not None or patch.remove_labels is not None:
        current = (await label_names(session, [item.id])).get(item.id, [])
        wanted = [n for n in current if n not in set(patch.remove_labels or [])]
        wanted += [n for n in (patch.add_labels or []) if n not in set(wanted)]
        kwargs["labels"] = wanted
    if kwargs:
        await update_item(session, item.id, ItemUpdate(**kwargs), actor=actor)
    if patch.archived is not None:
        await set_archived(session, item.id, patch.archived, actor)


async def bulk_update_items(
    session: AsyncSession, data: ItemBulkUpdate, actor: User
) -> BulkUpdateResult:
    result = BulkUpdateResult()
    seen: set[uuid.UUID] = set()
    for item_id in data.item_ids:
        if item_id in seen:
            continue
        seen.add(item_id)
        item = await session.get(WorkItem, item_id)
        if item is None:
            result.skipped.append(_skip(item_id, None, BulkSkipReason.NOT_FOUND))
            continue
        key = await _item_key(session, item)
        try:
            async with session.begin_nested():
                await _apply_one(session, item, data.patch, actor)
        except Exception as exc:  # classified, unknown ones logged: _skip_for
            result.skipped.append(_skip_for(
                exc, item_id, key, invalid_target=(ConflictError, NotFoundError), operation="update"
            ))
        else:
            result.updated.append(item_id)
    return result


# --- bulk move ---


async def _selected_items(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> list[WorkItem]:
    """The selected items, deduped, in selection order (unknown ids dropped)."""
    unique = list(dict.fromkeys(ids))
    rows = {
        row.id: row
        for row in (
            await session.execute(select(WorkItem).where(WorkItem.id.in_(unique)))
        ).scalars()
    }
    return [rows[item_id] for item_id in unique if item_id in rows]


async def _move_one(
    session: AsyncSession,
    item: WorkItem,
    source: Project,
    target: Project,
    target_states: dict[str, object],
    target_default_state,
    target_types: dict[str, uuid.UUID],
    target_type_default: uuid.UUID | None,
    target_field_keys: set[str],
    actor: User,
    permissions,
    target_permissions,
) -> BulkMovedItem:
    old_key = await _item_key(session, item)
    before = await _hydrate_one(session, item, source, actor, permissions)
    old_state_id = item.state_id

    # State by NAME, else a default of the same category, else the project default.
    old_state = await workflow.get_state(session, item.state_id)
    mapped_state = target_states.get(old_state.name.lower())
    if mapped_state is None:
        same_category = [
            s for s in target_states.values() if s.category == old_state.category
        ]
        mapped_state = same_category[0] if same_category else target_default_state

    # RADD-834: a move WRITES fields, so it runs the same checks as the
    # single-item path — builtin-field rules in BOTH projects (the restriction
    # may live where the item is, or where it lands), and custom-field write
    # grants for values the move drops (removing a value is a write).
    dropped = sorted(set(item.custom_fields) - target_field_keys)
    touched = {"state_id"}
    if item.release_id is not None:
        touched.add("release_id")
    await _check_builtin_field_rules(session, actor, source, permissions, touched)
    await _check_builtin_field_rules(session, actor, target, target_permissions, touched)
    if dropped:
        source_definitions = await fields.definitions_for_project(session, source)
        source_ctx = await _field_ctx(session, actor, source, permissions, source_definitions)
        fields.writable_check(source_definitions, {key: None for key in dropped}, source_ctx)

    item.state_id = mapped_state.id

    # Type by name, else the target default. Release is project-scoped: cleared.
    if item.type_id is not None:
        current_type = await itemtypes.get_type(session, item.type_id)
        item.type_id = target_types.get(current_type.name.lower(), target_type_default)
    else:
        item.type_id = target_type_default
    item.release_id = None

    if dropped:
        item.custom_fields = {
            k: v for k, v in item.custom_fields.items() if k in target_field_keys
        }

    item.number = await projects_service.allocate_item_number(session, target.id)
    item.project_id = target.id

    # Workflow guards (RADD-834): arriving is a transition into the mapped state
    # under the TARGET project's rules. Wildcard (from-any) rules fire — the
    # spec-112 "require a release to enter Done" shape — and a STRICT project
    # refuses arrivals with no wildcard edge, exactly as it refuses any
    # undefined transition. Checked after the patch is applied, like update_item.
    await workflow.check_transition(session, target, item, old_state_id, item.state_id)

    session.add(ItemKeyAlias(old_key=old_key.upper(), item_id=item.id))
    await session.flush()

    # RADD-1383: arriving is a state change like any other — the check plugins
    # hear about it through workflow, mirroring the single-item path.
    await workflow.state_moved(session, item.id, item.state_id)

    # The SOURCE permissions decide internal visibility on both sides of the diff.
    after = await _hydrate_one(session, item, target, actor, permissions)
    definitions = await fields.definitions_for_project(session, target)
    changes = diff_item_reads(before, after, field_names=field_name_map(definitions))
    changes.insert(0, {"field": "project", "from": source.key, "to": target.key})
    changes.insert(1, {"field": "key", "from": old_key, "to": after.key})
    # A cross-project move is still an item.updated, in `read._finish`'s shape.
    await events.emit(
        session,
        event_type=ItemEvent.UPDATED,
        entity_type=ItemEntity.ITEM,
        entity_id=item.id,
        actor_id=actor.id,
        payload={"item": event_item(after, target)},
        changes=changes,
    )
    return BulkMovedItem(
        item_id=item.id,
        old_key=old_key,
        new_key=after.key,
        dropped_fields=dropped,
    )


async def bulk_move_items(
    session: AsyncSession, data: ItemBulkMove, actor: User
) -> BulkMoveResult:
    target = await projects_service.get_project(session, data.target_project_id)
    target_permissions = await authz.require(
        session, actor, Permission.ITEM_CREATE, project=target
    )

    target_states = {s.name.lower(): s for s in await workflow.list_states(session, target.id)}
    target_default_state = await workflow.default_state(session, target.id)
    target_types = {
        t.name.lower(): t.id for t in await itemtypes.list_types(session, target.id)
    }
    default_type = await itemtypes.default_type(session, target.id)
    target_field_keys = {
        d.key for d in await fields.definitions_for_project(session, target)
    }

    selected_ids = [item.id for item in await _selected_items(session, data.item_ids)]
    projects: dict[uuid.UUID, Project] = {}
    perms: dict[uuid.UUID, frozenset[Permission]] = {}

    result = BulkMoveResult()
    target_id = target.id
    for item_id in selected_ids:
        # Re-fetched per iteration: a previous item's savepoint rollback expires
        # every instance that savepoint touched — the item, and the target
        # project whose item-number counter it incremented — and a sync
        # attribute access on an expired ORM object cannot lazy-load in async
        # context. `get` refreshes only when needed.
        item = await session.get(WorkItem, item_id)
        target = await session.get(Project, target_id)
        if item is None or item.project_id == target_id:
            continue  # gone, or already home — nothing to do
        source = projects.get(item.project_id)
        if source is None:
            source = await projects_service.get_project(session, item.project_id)
            projects[source.id] = source
            perms[source.id] = await authz.effective_permissions(session, actor, project=source)
        key = f"{source.key}-{item.number}"
        if Permission.ITEM_UPDATE not in perms[source.id]:
            result.skipped.append(_skip(item_id, key, BulkSkipReason.FORBIDDEN))
            continue
        try:
            async with session.begin_nested():
                moved = await _move_one(
                    session,
                    item,
                    source,
                    target,
                    target_states,
                    target_default_state,
                    target_types,
                    default_type.id if default_type else None,
                    target_field_keys,
                    actor,
                    perms[source.id],
                    target_permissions,
                )
        except Exception as exc:  # classified, unknown ones logged: _skip_for
            result.skipped.append(_skip_for(
                exc, item_id, key, invalid_target=(ConflictError,), operation="move"
            ))
        else:
            result.moved.append(moved)
    return result


# --- id listing (select all matching) ---




async def list_item_ids(
    session: AsyncSession,
    *,
    actor: User,
    filters: ItemListFilters,
    q: str | None = None,
) -> ItemIds:
    """Same filter surface + visibility as list_items, but ids only: the
    'select all N matching' seam. ids capped at bulk_max_items; total is the
    true visible count."""
    query, order = await visible_ids_query(session, actor=actor, filters=filters, q=q)
    total = await session.scalar(
        select(func.count()).select_from(query.order_by(None).subquery())
    )
    default_order = () if order else (WorkItem.rank.asc(),)
    ids_query = query.order_by(*order, *default_order, WorkItem.created_at.desc()).limit(
        settings.bulk_max_items
    )
    ids = list((await session.execute(ids_query)).scalars())
    return ItemIds(ids=ids, total=total or 0)


async def visible_matching_ids(
    session: AsyncSession,
    *,
    actor: User,
    q: str,
    project_id: uuid.UUID | None = None,
    candidate_ids: Sequence[uuid.UUID] | None = None,
) -> set[uuid.UUID]:
    """EVERY visible item id matching the SLQ query — uncapped, ids only.

    The reporting module's filter seam (the dashboard-wide SLQ): reports
    intersect their item universe with this set, so the query runs with the
    same visibility rules (RBAC, archived-hidden) as every other item read.
    Raises SlqError for a query that doesn't compile — same 422 as GET /items.
    """
    filters = ItemListFilters(project_id=project_id)
    query, _ = await visible_ids_query(session, actor=actor, filters=filters, q=q)
    if candidate_ids is not None:
        out = set()
        for batch in batched(dict.fromkeys(candidate_ids), 1000):
            out.update(await session.scalars(query.order_by(None).where(WorkItem.id.in_(batch))))
        return out
    return set((await session.execute(query.order_by(None))).scalars())


async def count_items(
    session: AsyncSession,
    *,
    actor: User,
    filters: ItemListFilters,
    q: str | None = None,
) -> int:
    """The visible-match count alone (spec 75 — GET /items/count, the slq_count
    widget's fetch): exactly list_item_ids' total without materializing ids."""
    query, _ = await visible_ids_query(session, actor=actor, filters=filters, q=q)
    total = await session.scalar(
        select(func.count()).select_from(query.order_by(None).subquery())
    )
    return total or 0
