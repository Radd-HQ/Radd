"""The write flows: create/update, archive/delete, stars, reorder, cycle moves."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.cycles import service as cycles_service
from radd.modules.events import service as events
from radd.modules.fields import service as fields
from radd.modules.fields.validation import apply_defaults, validate_custom_fields
from radd.modules.itemtypes import service as itemtypes
from radd.modules.projects import service as projects_service
from radd.modules.workflow import service as workflow
from radd.modules.workflow.models import State
from radd.modules.workflow.types import StateCategory

from radd.hooks import hooks

from ..enums import ItemEntity, ItemEvent, ItemKind, ItemVisibility
from ..hooks import ItemCreating, ItemHook
from ..models import ItemStar, WorkItem
from ..schemas import ItemCreate, ItemRankUpdate, ItemRead, ItemUpdate
from .links import sync_mention_links
from radd.clock import utcnow

from .queries import (
    _next_rank,
    _rebalance_ranks,
    _resolve_number,
    require_item,
)
from .read import _finish, _hydrate_one, get_item
from .relations import (
    _resolve_assignee,
    _resolve_cycle,
    _resolve_parent,
    _resolve_release,
    _resolve_state,
    _resolve_team,
    _resolve_type,
    _set_labels,
    _validate_dates,
)
from .visibility import _check_builtin_field_rules, _field_ctx, ensure_item_relation


# --- CRUD ---


async def _default_visibility(session: AsyncSession, project, explicit) -> str:
    """Spec 121: the filer's choice, else the project's `item_default_visibility`."""
    if explicit is not None:
        return explicit.value
    from radd.modules.settings import service as settings_service
    from radd.modules.settings.types import SettingKey

    value = await settings_service.resolve(
        session, SettingKey.ITEM_DEFAULT_VISIBILITY, project_id=project.id
    )
    return ItemVisibility(value).value


async def _refuse_self_lockout(
    session: AsyncSession, actor: User, item: WorkItem, permissions
) -> None:
    """Spec 121: a visibility change that would hide the issue from the person
    making it is refused (instance admins excepted, D1) — otherwise "restrict
    this" is a one-way door that closes behind you."""
    if authz.is_instance_admin(actor):
        return
    relations = authz.relations_held(permissions, Permission.ITEM_READ)
    relation_actor = await authz.relation_actor(session, actor)
    if not await authz.relation_holds_row_async(session, "item", relations, relation_actor, item):
        raise ConflictError(
            ItemEntity.ITEM,
            reason=(
                f"setting visibility to {item.visibility} would hide this issue from you — "
                "add yourself as a participant first, or ask an instance admin"
            ),
        )


async def create_item(session: AsyncSession, data: ItemCreate, actor: User) -> ItemRead:
    project = await projects_service.get_project(session, data.project_id)
    permissions = await authz.require(session, actor, Permission.ITEM_CREATE, project=project)
    await _check_builtin_field_rules(
        session, actor, project, permissions, data.model_fields_set
    )
    state = await _resolve_state(session, project, data.state_id)
    if data.type_id is not None:
        type_id = await _resolve_type(session, project, data.type_id)
    else:
        default = await itemtypes.default_type(session, project.id)
        type_id = default.id if default else None
    await _resolve_parent(session, data.kind, data.parent_id)
    # An import (project.manage) may name someone who has since left — see
    # `_resolve_assignee`. Ordinary creation still refuses a deactivated account.
    historical = Permission.PROJECT_MANAGE in permissions and data.created_at is not None
    if data.assignee_id is not None:
        await _resolve_assignee(session, data.assignee_id, allow_inactive=historical)
    if data.reporter_id is not None:
        await _resolve_assignee(session, data.reporter_id, allow_inactive=historical)
    if data.team_id is not None:
        await _resolve_team(session, project, data.team_id)
    if data.cycle_id is not None:
        await _resolve_cycle(session, project, data.cycle_id)
    if data.release_id is not None:
        await _resolve_release(session, project, data.release_id)
    _validate_dates(data.start_date, data.target_date)
    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)
    fields.writable_check(definitions, data.custom_fields, ctx)
    # Seed field default_values for keys the caller omitted (admin-set, so applied after
    # the writable check — a default may land on a field the creator can't write).
    custom_fields = validate_custom_fields(definitions, apply_defaults(definitions, data.custom_fields))
    number = await _resolve_number(session, project.id, data.number)
    next_rank = await _next_rank(session)  # append to the bottom of the manual order

    item = WorkItem(
        project_id=project.id,
        number=number,
        kind=data.kind.value,
        type_id=type_id,
        parent_id=data.parent_id,
        title=data.title,
        description=data.description,
        state_id=state.id,
        priority=data.priority.value,
        assignee_id=data.assignee_id,
        # model_fields_set idiom (spec 62): omitted = the acting user raised it;
        # an EXPLICIT null keeps it unset (external/public submits have no user).
        reporter_id=(
            data.reporter_id if "reporter_id" in data.model_fields_set else actor.id
        ),
        team_id=data.team_id,
        start_date=data.start_date,
        target_date=data.target_date,
        cycle_id=data.cycle_id,
        release_id=data.release_id,
        flagged=data.flagged,
        visibility=await _default_visibility(session, project, data.visibility),
        estimate_points=data.estimate_points,
        rank=next_rank,
        custom_fields=custom_fields,
    )
    # Import (project.manage): stamp the original creation time + credit the
    # reporter as the creator in the history feed, instead of the importer/now.
    occurred_at = None
    event_actor_id = None
    if data.created_at is not None and Permission.PROJECT_MANAGE in permissions:
        occurred_at = data.created_at.replace(tzinfo=None)
        item.created_at = occurred_at
        # The source's LAST-TOUCHED time when the importer knows it; otherwise the
        # creation time, so an import never stamps `now()` on historical rows.
        item.updated_at = (
            data.updated_at.replace(tzinfo=None) if data.updated_at is not None else occurred_at
        )
        event_actor_id = item.reporter_id
    # Spec 119: the row, its stint, its labels, its mentions and the hook that
    # may REFUSE all of it, in one savepoint.
    #
    # The hook is the last moment a creation can be turned down, and a handler
    # that raises has to leave nothing behind. Without the savepoint that was
    # only true for callers who let the exception reach a transaction boundary:
    # a caller that catches and carries on — the Jira importer's per-issue
    # `except Exception` is exactly that shape — kept the flushed row and
    # committed it with the batch, so a refused draft became a half-created
    # orphan with no event and no labels-of-record. Rolling back to here makes
    # the promise true for every caller, whatever it does with the error.
    guard = await session.begin_nested()
    try:
        session.add(item)
        await session.flush()
        if item.cycle_id is not None:
            # Open the first cycle stint (spec 56) — import stamps original time.
            await cycles_service.record_cycle_change(
                session, item_id=item.id, old_cycle_id=None, new_cycle_id=item.cycle_id,
                at=occurred_at,
            )
        await _set_labels(session, item, data.labels, actor.id)
        await sync_mention_links(session, item)  # derive #[…] backlinks from title/description
        # `items` knows nothing about who listens — the dispatch is a no-op with
        # no subscriber registered.
        await hooks.dispatch(
            session, ItemHook.CREATING, ItemCreating(item=item, project=project, actor=actor)
        )
    except BaseException:
        await guard.rollback()
        raise
    await guard.commit()
    return await _finish(
        session, item, project, ItemEvent.CREATED, actor, ctx, definitions, permissions,
        occurred_at=occurred_at, event_actor_id=event_actor_id,
    )


async def update_item(
    session: AsyncSession, item_id: uuid.UUID, data: ItemUpdate, actor: User
) -> ItemRead:
    item = await require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    permissions = await authz.require(session, actor, Permission.ITEM_UPDATE, project=project)
    await ensure_item_relation(session, actor, item, permissions, Permission.ITEM_UPDATE)
    await _check_builtin_field_rules(session, actor, project, permissions, data.model_fields_set)
    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)
    before = await _hydrate_one(session, item, project, actor, permissions)
    old_state_id = item.state_id

    if data.title is not None:
        item.title = data.title
    if data.description is not None:
        item.description = data.description
    if data.state_id is not None:
        item.state_id = (await _resolve_state(session, project, data.state_id)).id
    if data.priority is not None:
        item.priority = data.priority.value
    # Nullable relations: omitted = unchanged, explicit null = clear.
    if "type_id" in data.model_fields_set:
        item.type_id = await _resolve_type(session, project, data.type_id)
    if "parent_id" in data.model_fields_set:
        await _resolve_parent(session, ItemKind(item.kind), data.parent_id)
        item.parent_id = data.parent_id
    # A re-import refreshing a historical row may restate an assignee/reporter who
    # has since left, exactly as the create path does.
    historical = Permission.PROJECT_MANAGE in permissions and data.updated_at is not None
    if "assignee_id" in data.model_fields_set:
        if data.assignee_id is not None:
            await _resolve_assignee(session, data.assignee_id, allow_inactive=historical)
        item.assignee_id = data.assignee_id
    if "reporter_id" in data.model_fields_set:
        if data.reporter_id is not None:
            await _resolve_assignee(session, data.reporter_id, allow_inactive=historical)
        item.reporter_id = data.reporter_id
    if "team_id" in data.model_fields_set:
        if data.team_id is not None:
            await _resolve_team(session, project, data.team_id)
        item.team_id = data.team_id
    if "cycle_id" in data.model_fields_set:
        if data.cycle_id is not None:
            await _resolve_cycle(session, project, data.cycle_id)
        # Cycle stint history (spec 56): close the old stint, open the new one —
        # this is what makes carryovers (complete-cycle moves) queryable later.
        await cycles_service.record_cycle_change(
            session, item_id=item.id, old_cycle_id=item.cycle_id, new_cycle_id=data.cycle_id
        )
        item.cycle_id = data.cycle_id
    if "release_id" in data.model_fields_set:
        if data.release_id is not None:
            await _resolve_release(session, project, data.release_id)
        item.release_id = data.release_id
    if data.flagged is not None:
        item.flagged = data.flagged
    if data.visibility is not None and data.visibility.value != item.visibility:
        item.visibility = data.visibility.value
        await _refuse_self_lockout(session, actor, item, permissions)
    if "estimate_points" in data.model_fields_set:  # spec 70 — explicit null clears
        item.estimate_points = data.estimate_points
    if "start_date" in data.model_fields_set:
        item.start_date = data.start_date
    if "target_date" in data.model_fields_set:
        item.target_date = data.target_date
    # Validate against the resulting values (either side may have just changed).
    _validate_dates(item.start_date, item.target_date)
    if data.custom_fields is not None:
        fields.writable_check(definitions, data.custom_fields, ctx)
        merged = {**item.custom_fields, **data.custom_fields}
        item.custom_fields = validate_custom_fields(definitions, merged)
    if data.labels is not None:
        await _set_labels(session, item, data.labels, actor.id)

    # Workflow transition guards (spec 61): checked AFTER every patch field is
    # applied (values arriving in the same PATCH count) and only on a REAL state
    # change. Applies to every actor including automations/SYSTEM.
    if item.state_id != old_state_id:
        await workflow.check_transition(session, project, item, old_state_id, item.state_id)

    # Import (project.manage): restore the source's last-touched time. Assigning
    # the attribute puts it in the UPDATE's SET clause, which is what suppresses
    # the column's `onupdate=now()` — otherwise a re-import would silently stamp
    # every issue as touched today.
    occurred_at = None
    if data.updated_at is not None and Permission.PROJECT_MANAGE in permissions:
        occurred_at = data.updated_at.replace(tzinfo=None)
        item.updated_at = occurred_at

    await session.flush()
    if item.state_id != old_state_id:
        # Approvals (spec 71): a successful move into an approved target CONSUMES
        # the request (one approval unlocks one move). Soft dep — module optional.
        try:
            from radd.modules.approvals import service as approvals_service
        except ImportError:
            pass
        else:
            await approvals_service.consume(session, item.id, item.state_id)
    if data.title is not None or data.description is not None:
        await sync_mention_links(session, item)  # text changed → re-derive #[…] backlinks
    # The EVENT carries the historical time too, not just the row: item history,
    # the audit log and every report (throughput, CFD, time-in-state) are built
    # from the event stream, so a restated `updated_at` that left its event
    # stamped `now()` would file the whole import under today. Mirrors create.
    return await _finish(
        session, item, project, ItemEvent.UPDATED, actor, ctx, definitions, permissions,
        before=before, occurred_at=occurred_at,
    )


async def reassign_state(
    session: AsyncSession, from_state_id: uuid.UUID, to_state_id: uuid.UUID, actor: User
) -> int:
    """Every item in `from_state` moves to `to_state` — the state-DELETION
    repair (RADD-853, the spec-89 delete-with-successor precedent). Authorized
    by the CALLER's state.delete gate, not per-item item.update, and it
    deliberately BYPASSES transition guards: a guard refusing half the items
    would strand the deletion mid-way, and the successor is explicit. Emits an
    ordinary item.updated per item (with a before snapshot), so history,
    watchers, search and reports see the move honestly. Returns the count."""
    result = await session.execute(select(WorkItem).where(WorkItem.state_id == from_state_id))
    items = list(result.scalars())
    if not items:
        return 0
    project = await projects_service.get_project(session, items[0].project_id)
    permissions = await authz.effective_permissions(session, actor, project=project)
    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)
    for item in items:
        before = await _hydrate_one(session, item, project, actor, permissions)
        item.state_id = to_state_id
        await session.flush()
        await _finish(
            session, item, project, ItemEvent.UPDATED, actor, ctx, definitions, permissions,
            before=before,
        )
    return len(items)


async def set_archived(
    session: AsyncSession, item_id: uuid.UUID, archived: bool, actor: User
) -> ItemRead:
    """Soft archive/unarchive (spec 38) — hidden from lists by default, still
    reachable by key/detail. An ordinary item.updated with an `archived` diff."""
    item = await require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    permissions = await authz.require(session, actor, Permission.ITEM_UPDATE, project=project)
    await ensure_item_relation(session, actor, item, permissions, Permission.ITEM_UPDATE)
    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)
    before = await _hydrate_one(session, item, project, actor, permissions)
    item.archived_at = utcnow() if archived else None
    await session.flush()
    return await _finish(
        session, item, project, ItemEvent.UPDATED, actor, ctx, definitions, permissions, before=before
    )


async def delete_item(session: AsyncSession, item_id: uuid.UUID, actor: User) -> None:
    """Hard delete (spec 38): gated by `item.delete` (spec 50 — was project.manage,
    which still implies it), children must be gone first (the parent FK restricts),
    dependents CASCADE. The event log's rows for the item remain — the audit trail
    survives the row.

    RADD-717: comments no longer carry a foreign key to work_items (the column is
    polymorphic), so the CASCADE that used to take them is gone and they are
    removed explicitly. Missing this leaves rows nothing can reach."""
    item = await require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    delete_permissions = await authz.require(
        session, actor, Permission.ITEM_DELETE, project=project
    )
    await ensure_item_relation(session, actor, item, delete_permissions, Permission.ITEM_DELETE)
    child_count = await session.scalar(
        select(func.count()).select_from(WorkItem).where(WorkItem.parent_id == item_id)
    )
    if child_count:
        raise ConflictError(
            ItemEntity.ITEM,
            reason=f"item has {child_count} child item(s) — delete or re-parent them first",
        )
    # The full ref, like every other item-scoped event (RADD-922). It used to be
    # three hand-picked fields, so a webhook receiver saw a completely different
    # object on delete than on update — and the item is gone a line later, which
    # is exactly when a consumer cannot go and look the rest up.
    # Emitted while the row is still present (the delete is ~15 lines down), so
    # the kernel resolves the subject normally — a delete event is exactly when a
    # consumer cannot go and look the rest up afterwards.
    await events.emit(
        session,
        event_type=ItemEvent.DELETED,
        entity_type=ItemEntity.ITEM,
        entity_id=item.id,
        actor_id=actor.id,
        subjects={"item": item.id},
    )
    # RADD-717: the polymorphic comment column carries no FK, so its rows do not
    # cascade with the item. Deferred import — items must not depend on comments
    # at module scope (comments already depends on items).
    from radd.modules.comments import service as comments_service
    from radd.modules.comments.types import CommentParentType

    await comments_service.delete_for_parent(session, CommentParentType.ITEM.value, item.id)
    await session.delete(item)
    await session.flush()


# --- stars (spec 24) ---


async def _require_readable(session: AsyncSession, item_id: uuid.UUID, actor: User) -> None:
    """Star/unstar only need to SEE the item (item.read on its project)."""
    item = await require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, actor, Permission.ITEM_READ, project=project)


async def star_item(session: AsyncSession, item_id: uuid.UUID, actor: User) -> ItemRead:
    """Personal star (spec 24) — idempotent; no event (per-user, not shared state)."""
    await _require_readable(session, item_id, actor)
    if await session.get(ItemStar, (actor.id, item_id)) is None:
        session.add(ItemStar(user_id=actor.id, item_id=item_id))
        await session.flush()
    return await get_item(session, item_id, actor)


async def unstar_item(session: AsyncSession, item_id: uuid.UUID, actor: User) -> None:
    await _require_readable(session, item_id, actor)
    star = await session.get(ItemStar, (actor.id, item_id))
    if star is not None:
        await session.delete(star)
        await session.flush()


# --- manual ranking (spec 24) ---


async def reorder_item(
    session: AsyncSession, item_id: uuid.UUID, data: ItemRankUpdate, actor: User
) -> ItemRead:
    """Set an item's manual rank between two neighbours (drag-to-rank, spec 24)."""
    item = await require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    permissions = await authz.require(session, actor, Permission.ITEM_UPDATE, project=project)
    await ensure_item_relation(session, actor, item, permissions, Permission.ITEM_UPDATE)

    async def rank_of(neighbour_id: uuid.UUID | None) -> float | None:
        if neighbour_id is None or neighbour_id == item_id:
            return None
        return (
            await session.execute(select(WorkItem.rank).where(WorkItem.id == neighbour_id))
        ).scalar()

    after = await rank_of(data.after_id)
    before = await rank_of(data.before_id)

    if after is not None and before is not None:
        new_rank = (after + before) / 2
        if new_rank <= after or new_rank >= before:  # float gap collapsed → respace + retry
            await _rebalance_ranks(session)
            after = await rank_of(data.after_id)
            before = await rank_of(data.before_id)
            new_rank = ((after or 0.0) + (before or 0.0)) / 2
    elif before is not None:  # move to the top of the bucket
        new_rank = before - settings.item_rank_step
    elif after is not None:  # move to the bottom of the bucket
        new_rank = after + settings.item_rank_step
    else:  # no neighbours resolved — nothing to do
        return await get_item(session, item_id, actor)

    item.rank = new_rank
    await session.flush()
    definitions = await fields.definitions_for_project(session, project)
    ctx = await _field_ctx(session, actor, project, permissions, definitions)
    return await _finish(session, item, project, ItemEvent.UPDATED, actor, ctx, definitions, permissions)


# --- cycle seams ---


async def move_open_cycle_items(
    session: AsyncSession,
    cycle_id: uuid.UUID,
    target_cycle_id: uuid.UUID | None,
    actor: User,
) -> int:
    """Sprint-close seam (cycles.complete_cycle): re-home every OPEN item — state
    category not done/canceled, not archived — from `cycle_id` to `target_cycle_id`
    (None = backlog). Goes through update_item per item so authz, builtin-field
    rules, events, history and realtime all apply; a raised error aborts the whole
    request transaction, keeping the close atomic."""
    stmt = (
        select(WorkItem.id)
        .join(State, WorkItem.state_id == State.id)
        .where(
            WorkItem.cycle_id == cycle_id,
            WorkItem.archived_at.is_(None),
            State.category.notin_([StateCategory.DONE, StateCategory.CANCELED]),
        )
    )
    item_ids = list((await session.execute(stmt)).scalars())
    for item_id in item_ids:
        await update_item(session, item_id, ItemUpdate(cycle_id=target_cycle_id), actor=actor)
    return len(item_ids)
