"""Bulk operations (spec 68): batch edit, cross-project move, id listing.

Bulk edits route through the single-item service (`update_item`/`set_archived`)
per item, so RBAC, builtin-field rules, transition guards, events, automations,
notify, search and realtime keep their exact semantics — this layer only adds
iteration, a SAVEPOINT per item, and skip-and-report (one bad item never fails
the batch). Moves re-key items into the target project with name-based
state/type mapping and write `item_key_aliases` rows so old URLs keep resolving.
A move moves EXACTLY the selected items (spec 80): the hierarchy is
global now, so parent/child links survive a cross-project move and
children stay where they are unless also selected.
"""

import logging
import uuid
from collections.abc import Sequence

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

from . import slq
from .changes import diff_item_reads, field_name_map
from .enums import BulkSkipReason, ItemEntity, ItemEvent
from .filters import ItemListFilters
from .hydration import hydrate, label_names
from .listing import apply_filters, cf_definitions
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

# Package-private helper — reached through its concern module, not the service
# barrel, which exports only the items module's public surface.
from .service.visibility import _internal_visible
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
        except ForbiddenError:
            result.skipped.append(_skip(item_id, key, BulkSkipReason.FORBIDDEN))
        except TransitionError as exc:
            result.skipped.append(
                _skip(item_id, key, BulkSkipReason.TRANSITION_BLOCKED, "; ".join(exc.errors))
            )
        except (ConflictError, NotFoundError) as exc:
            # A project-scoped value (state/type/release…) that doesn't apply to
            # this item's project — expected when a selection spans projects.
            result.skipped.append(
                _skip(item_id, key, BulkSkipReason.INVALID_TARGET, str(exc))
            )
        except Exception:
            logger.exception("bulk-update failed for item %s", item_id)
            result.skipped.append(_skip(item_id, key, BulkSkipReason.ERROR))
        else:
            result.updated.append(item_id)
    return result


# --- bulk move ---


async def _selected_items(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> list[WorkItem]:
    """The selected items, deduped, in selection order (unknown ids dropped).
    Spec 80 removed the descendant auto-include: the hierarchy is
    global, so a move takes EXACTLY the selection — parent links
    survive the project change and children stay unless also selected."""
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
) -> BulkMovedItem:
    old_key = await _item_key(session, item)
    before = (
        await hydrate(
            session,
            [item],
            internal_visible=_internal_visible({source.id: permissions}),
            actor_id=actor.id,
        )
    )[0]

    # `parent_id` is untouched: the hierarchy spans projects (spec 80), so
    # the link stays valid across the project change — validity is already
    # enforced by the caller's target check.

    # State by NAME, else a default of the same category, else the project default.
    old_state = await workflow.get_state(session, item.state_id)
    mapped_state = target_states.get(old_state.name.lower())
    if mapped_state is None:
        same_category = [
            s for s in target_states.values() if s.category == old_state.category
        ]
        mapped_state = same_category[0] if same_category else target_default_state
    item.state_id = mapped_state.id

    # Type by name, else the target default. Release is project-scoped: cleared.
    if item.type_id is not None:
        current_type = await itemtypes.get_type(session, item.type_id)
        item.type_id = target_types.get(current_type.name.lower(), target_type_default)
    else:
        item.type_id = target_type_default
    item.release_id = None

    dropped = sorted(set(item.custom_fields) - target_field_keys)
    if dropped:
        item.custom_fields = {
            k: v for k, v in item.custom_fields.items() if k in target_field_keys
        }

    item.number = await projects_service.allocate_item_number(session, target.id)
    item.project_id = target.id
    session.add(ItemKeyAlias(old_key=old_key.upper(), item_id=item.id))
    await session.flush()

    after = (
        await hydrate(
            session,
            [item],
            internal_visible=_internal_visible({target.id: permissions}),
            actor_id=actor.id,
        )
    )[0]
    definitions = await fields.definitions_for_project(session, target)
    changes = diff_item_reads(before, after, field_names=field_name_map(definitions))
    changes.insert(0, {"field": "project", "from": source.key, "to": target.key})
    changes.insert(1, {"field": "key", "from": old_key, "to": after.key})
    payload = after.model_dump(mode="json")
    payload["changes"] = changes
    await events.emit(
        session,
        event_type=ItemEvent.UPDATED,
        entity_type=ItemEntity.ITEM,
        entity_id=item.id,
        actor_id=actor.id,
        payload=payload,
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
    await authz.require(session, actor, Permission.ITEM_CREATE, project=target)

    target_states = {s.name.lower(): s for s in await workflow.list_states(session, target.id)}
    target_default_state = await workflow.default_state(session, target.id)
    target_types = {
        t.name.lower(): t.id for t in await itemtypes.list_types(session, target.id)
    }
    default_type = await itemtypes.default_type(session, target.id)
    target_field_keys = {
        d.key for d in await fields.definitions_for_project(session, target)
    }

    items = await _selected_items(session, data.item_ids)
    projects: dict[uuid.UUID, Project] = {}
    perms: dict[uuid.UUID, frozenset[Permission]] = {}

    result = BulkMoveResult()
    for item in items:
        if item.project_id == target.id:
            continue  # already home — nothing to do
        source = projects.get(item.project_id)
        if source is None:
            source = await projects_service.get_project(session, item.project_id)
            projects[source.id] = source
            perms[source.id] = await authz.effective_permissions(session, actor, project=source)
        key = f"{source.key}-{item.number}"
        if Permission.ITEM_UPDATE not in perms[source.id]:
            result.skipped.append(_skip(item.id, key, BulkSkipReason.FORBIDDEN))
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
                )
        except ConflictError as exc:
            result.skipped.append(
                _skip(item.id, key, BulkSkipReason.INVALID_TARGET, str(exc))
            )
        except Exception:
            logger.exception("bulk-move failed for item %s", item.id)
            result.skipped.append(_skip(item.id, key, BulkSkipReason.ERROR))
        else:
            result.moved.append(moved)
    return result


# --- id listing (select all matching) ---


async def _visible_ids_query(
    session: AsyncSession,
    *,
    actor: User,
    filters: ItemListFilters,
    q: str | None,
):
    """The shared SELECT WorkItem.id builder behind /items/ids and /items/count:
    same filter surface + visibility as list_items. Returns (query, slq_order)."""
    scoped_project: Project | None = None
    if filters.project_id:
        scoped_project = await projects_service.get_project(session, filters.project_id)
        await authz.require(session, actor, Permission.ITEM_READ, project=scoped_project)
    else:
        readable = await authz.require_anywhere(session, actor, Permission.ITEM_READ)

    query = select(WorkItem.id)
    if scoped_project is None:
        # Cross-project: constrain to projects the actor can read UP FRONT so
        # both the count and the ids honor visibility (RADD-672: item.read
        # anywhere, not the global atom a scoped key never holds).
        query = query.where(WorkItem.project_id.in_(readable.keys()))
    query = await apply_filters(session, query, filters, scoped_project)
    order: tuple = ()
    if q and q.strip():
        compiled = await slq.compile_query(
            session,
            slq.parse(q),
            definitions_by_key=await cf_definitions(session, scoped_project),
            current_user_id=actor.id,
            project_id=filters.project_id,
        )
        if compiled.where is not None:
            query = query.where(compiled.where)
        order = compiled.order
    return query, order


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
    query, order = await _visible_ids_query(session, actor=actor, filters=filters, q=q)
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
) -> set[uuid.UUID]:
    """EVERY visible item id matching the SLQ query — uncapped, ids only.

    The reporting module's filter seam (the dashboard-wide SLQ): reports
    intersect their item universe with this set, so the query runs with the
    same visibility rules (RBAC, archived-hidden) as every other item read.
    Raises SlqError for a query that doesn't compile — same 422 as GET /items.
    """
    filters = ItemListFilters(project_id=project_id)
    query, _ = await _visible_ids_query(session, actor=actor, filters=filters, q=q)
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
    query, _ = await _visible_ids_query(session, actor=actor, filters=filters, q=q)
    total = await session.scalar(
        select(func.count()).select_from(query.order_by(None).subquery())
    )
    return total or 0
