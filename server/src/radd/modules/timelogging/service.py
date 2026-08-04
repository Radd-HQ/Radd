"""Worklogs + per-item estimate/summary. The module's core write path.

Estimate/logged live in this module's own tables (see models) so the items module
never depends on time logging — the plugin stays per-project-optional.
"""

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ForbiddenError, ConflictError, NotFoundError
from radd.modules.auth import authz, service as auth_service
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from . import categories, enablement
from .duration import format_duration, parse_duration
from .models import ItemEstimate, Worklog
from .schemas import (
    CategoryRef,
    EstimateSet,
    GeneralWorklogCreate,
    ItemTimeBatchEntry,
    ItemTimeSummary,
    UserRef,
    WorklogCreate,
    WorklogRead,
    WorklogUpdate,
)
from .types import TimelogEntity, WorklogEvent


def _parse(text: str, hours_per_day: int) -> int:
    return parse_duration(
        text,
        hours_per_day=hours_per_day,
        days_per_week=settings.timelog_days_per_week,
    )


def _fmt(seconds: int, hours_per_day: int) -> str:
    return format_duration(
        seconds,
        hours_per_day=hours_per_day,
        days_per_week=settings.timelog_days_per_week,
    )


async def _hours_per_day(session: AsyncSession) -> int:
    """The '1d'==N hours factor — GLOBAL since the spec-67 follow-up (instance
    override → env default; the per-project override is retired so a duration
    means the same thing on every timesheet row and cycle handle)."""
    from radd.modules.settings import service as settings_service
    from radd.modules.settings.types import SettingKey

    return await settings_service.resolve(session, SettingKey.TIMELOG_HOURS_PER_DAY)


async def nav_timesheet_visible(session: AsyncSession, user) -> bool:
    """THE definition of "is the Timesheet area useful to this actor"
    (RADD-843): timesheet.view held anywhere (they review others' time), OR
    any READABLE project has time logging enabled (they could log), OR they
    have worklog rows at all (general/itemless worklogs exist, spec 59 — a
    timesheet.view-less actor with history still needs their own sheet).
    Access ∧ usefulness — never a feature flag alone."""
    from sqlalchemy import exists as sa_exists, select as sa_select

    from .models import ProjectTimeLogging

    if await authz.holds(session, user, authz.Permission.TIMESHEET_VIEW, any_project=True):
        return True
    # "They could log" means worklog.write SOMEWHERE with logging enabled
    # there — not "some readable project logs time": since RADD-825 the floor
    # makes every project readable-in-part (item.read@own), which would light
    # this arm for accounts that cannot log a minute anywhere (RADD-835).
    writable = await authz.require_anywhere(session, user, authz.Permission.WORKLOG_WRITE)
    if writable:
        enabled = await session.scalar(
            sa_select(ProjectTimeLogging.project_id)
            .where(
                ProjectTimeLogging.project_id.in_(writable.keys()),
                ProjectTimeLogging.enabled.is_(True),
            )
            .limit(1)
        )
        if enabled is not None:
            return True
    has_rows = await session.scalar(
        sa_select(sa_exists().where(Worklog.author_id == user.id))
    )
    return bool(has_rows)


async def worklog_scope(
    session: AsyncSession, worklog: Worklog
) -> object | None:
    """The project a worklog is anchored to (spec 59), or None for a bare
    itemless entry: via its item, its project, else None."""
    if worklog.item_id is not None:
        _, project = await _project_for_item(session, worklog.item_id)
        return project
    if worklog.project_id is not None:
        return await projects_service.get_project(session, worklog.project_id)
    return None


# --- worklogs ---


async def get_worklog(session: AsyncSession, worklog_id: uuid.UUID) -> Worklog:
    worklog = await session.get(Worklog, worklog_id)
    if worklog is None:
        raise NotFoundError(TimelogEntity.WORKLOG, worklog_id)
    return worklog


async def worklogs_for_item(session: AsyncSession, item_id: uuid.UUID) -> list[Worklog]:
    result = await session.execute(
        select(Worklog)
        .where(Worklog.item_id == item_id)
        .order_by(Worklog.worked_on.desc(), Worklog.created_at.desc())
    )
    return list(result.scalars())


async def logged_seconds(session: AsyncSession, item_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(Worklog.time_spent_seconds), 0)).where(
            Worklog.item_id == item_id
        )
    )
    return int(total or 0)


async def logged_seconds_by_items(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Batched Σ logged per item — the epic-rollup seam (spec 76). Items with no
    worklogs are simply absent. One grouped query, never per item."""
    ids = set(item_ids)
    if not ids:
        return {}
    rows = await session.execute(
        select(Worklog.item_id, func.sum(Worklog.time_spent_seconds))
        .where(Worklog.item_id.in_(ids))
        .group_by(Worklog.item_id)
    )
    return {item_id: int(total or 0) for item_id, total in rows.all()}


async def estimate_seconds_by_items(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Batched original-estimate seconds per item (spec 76 rollup seam); items
    without an estimate row are absent."""
    ids = set(item_ids)
    if not ids:
        return {}
    rows = await session.execute(
        select(ItemEstimate.item_id, ItemEstimate.original_estimate_seconds).where(
            ItemEstimate.item_id.in_(ids)
        )
    )
    return {item_id: seconds for item_id, seconds in rows.all()}


async def timelog_batch(
    session: AsyncSession, actor: User, item_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, ItemTimeBatchEntry]:
    """Batched estimate/logged seconds for a page of roadmap items (spec 78 —
    auto-schedule durations). The request is filtered to items the actor can
    read (the sla/batch idiom); readable ids ALWAYS appear, so None/0 means "no
    estimate / nothing logged" rather than "not allowed". Reuses the spec-76
    grouped-query seams — never per item."""
    item_map = await items_service.items_by_ids(session, list(dict.fromkeys(item_ids)))
    projects: dict[uuid.UUID, Project] = {}
    for item in item_map.values():
        if item.project_id not in projects:
            projects[item.project_id] = await projects_service.get_project(
                session, item.project_id
            )
    permissions = await authz.permissions_for_projects(
        session, actor, list(projects.values())
    )
    readable = [
        item.id
        for item in item_map.values()
        if authz.holds_base(permissions.get(item.project_id, frozenset()), authz.Permission.ITEM_READ)
    ]
    estimates = await estimate_seconds_by_items(session, readable)
    logged = await logged_seconds_by_items(session, readable)
    return {
        item_id: ItemTimeBatchEntry(
            estimate_seconds=estimates.get(item_id),
            logged_seconds=logged.get(item_id, 0),
        )
        for item_id in readable
    }


async def _project_for_item(session: AsyncSession, item_id: uuid.UUID):
    item = await items_service.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    return item, project


async def hydrate(
    session: AsyncSession, worklogs: Sequence[Worklog], hours_per_day: int
) -> list[WorklogRead]:
    """Batch-hydrate author + category names (no N+1). `hours_per_day` formats the
    duration strings through the caller's resolved cascade value."""
    if not worklogs:
        return []
    authors = await auth_service.users_by_ids(session, {w.author_id for w in worklogs})
    cats = await categories.categories_by_ids(
        session, {w.category_id for w in worklogs if w.category_id}
    )
    reads: list[WorklogRead] = []
    for w in worklogs:
        author = authors.get(w.author_id)
        category = cats.get(w.category_id) if w.category_id else None
        reads.append(
            WorklogRead(
                id=w.id,
                item_id=w.item_id,
                project_id=w.project_id,
                author=UserRef(id=w.author_id, name=author.name if author else "?"),
                category=CategoryRef(id=category.id, name=category.name) if category else None,
                worked_on=w.worked_on,
                time_spent_seconds=w.time_spent_seconds,
                time_spent=_fmt(w.time_spent_seconds, hours_per_day),
                note=w.note,
                created_at=w.created_at,
                updated_at=w.updated_at,
            )
        )
    return reads


async def create_worklog(
    session: AsyncSession,
    item_id: uuid.UUID,
    data: WorklogCreate,
    author_id: uuid.UUID,
    today: date,
    created_at: datetime | None = None,
) -> WorklogRead:
    item, project = await _project_for_item(session, item_id)
    await enablement.require_enabled(session, project.id)
    hpd = await _hours_per_day(session)
    if data.category_id is not None:
        await categories.resolve_category(session, data.category_id)
    # `data.author_id` is the IMPORT path stating who actually logged the time.
    # It was accepted by the schema and then ignored here, so every imported
    # worklog was credited to whoever ran the import (spec 90 follow-up,
    #). The `author_id` argument stays the default for normal use.
    logged_by = data.author_id or author_id
    worklog = Worklog(
        item_id=item_id,
        author_id=logged_by,
        category_id=data.category_id,
        worked_on=data.worked_on or today,
        time_spent_seconds=_parse(data.time_spent, hpd),
        note=data.note,
    )
    if created_at is not None:  # import: when the work was logged (naive UTC)
        worklog.created_at = created_at.replace(tzinfo=None)
    session.add(worklog)
    await session.flush()
    await _emit(
        session, WorklogEvent.CREATED, worklog, logged_by, occurred_at=created_at,
    )
    return (await hydrate(session, [worklog], hpd))[0]


async def create_general_worklog(
    session: AsyncSession,
    data: GeneralWorklogCreate,
    author_id: uuid.UUID,
    today: date,
) -> WorklogRead:
    """Itemless entry (spec 59) — anchored to an optional project, category
    REQUIRED (schema + the ck_worklogs_scope constraint)."""
    project = None
    if data.project_id is not None:
        project = await projects_service.get_project(session, data.project_id)
        await enablement.require_enabled(session, project.id)
    await categories.resolve_category(session, data.category_id)
    hpd = await _hours_per_day(session)
    worklog = Worklog(
        item_id=None,
        project_id=project.id if project else None,
        author_id=author_id,
        category_id=data.category_id,
        worked_on=data.worked_on or today,
        time_spent_seconds=_parse(data.time_spent, hpd),
        note=data.note,
    )
    session.add(worklog)
    await session.flush()
    await _emit(session, WorklogEvent.CREATED, worklog, author_id)
    return (await hydrate(session, [worklog], hpd))[0]


async def can_log_general(session: AsyncSession, user) -> bool:
    """May log itemless general time: holds worklog.write on >= 1 project (spec 59).

    Public because MCP needs the same answer the router does (RADD-741) — two
    copies of "who may touch this worklog" is exactly the drift that lets an
    agent do something the UI forbids, or vice versa.
    """
    from radd.modules.auth import authz
    from radd.modules.projects import service as projects_service

    projects = await projects_service.list_projects(session)
    perms_by_project = await authz.permissions_for_projects(session, user, projects)
    return any(authz.Permission.WORKLOG_WRITE in perms for perms in perms_by_project.values())


async def authorize_mutation(session: AsyncSession, user, worklog, *, others) -> None:
    """Author (with worklog.write) or a holder of `others` may edit/delete a
    worklog (spec 50: worklog.delete to delete, project.manage to edit another's;
    spec 59: itemless entries need the general-log gate for the author and
    `others` at global scope for anyone else).

    Lives in the service, not the router, so the MCP tools enforce the SAME rule
    rather than a second reading of it.
    """
    from radd.modules.auth import authz

    project = await worklog_scope(session, worklog)
    is_author = worklog.author_id == user.id
    if project is not None:
        perms = await authz.effective_permissions(session, user, project=project)
    else:
        perms = await authz.effective_permissions(session, user)
    if others is authz.Permission.WORKLOG_DELETE:
        # RADD-816 (Q4): the author-own right is the Baseline's
        # `worklog.delete@own` grant — relation-resolved, inspector-explainable,
        # revocable. The hardcoded author arm is gone.
        relations = authz.relations_held(perms, authz.Permission.WORKLOG_DELETE)
        if relations:
            if authz.RELATION_ANY in relations:
                return
            relation_actor = await authz.relation_actor(session, user)
            if authz.relation_holds_row("worklog", relations, relation_actor, worklog):
                return
        raise ForbiddenError("you may only delete your own worklogs here")
    if project is not None:
        if (is_author and authz.Permission.WORKLOG_WRITE in perms) or (others in perms):
            return
    else:
        if is_author and await can_log_general(session, user):
            return
        if others in perms:
            return
    raise ForbiddenError("only the worklog's author or a project manager may change it")


async def update_worklog(
    session: AsyncSession, worklog: Worklog, data: WorklogUpdate, actor_id: uuid.UUID
) -> WorklogRead:
    hpd = await _hours_per_day(session)
    if data.time_spent is not None:
        worklog.time_spent_seconds = _parse(data.time_spent, hpd)
    if data.worked_on is not None:
        worklog.worked_on = data.worked_on
    if data.note is not None:
        worklog.note = data.note
    if "category_id" in data.model_fields_set:  # explicit null clears it
        if data.category_id is not None:
            await categories.resolve_category(session, data.category_id)
        elif worklog.item_id is None:
            # Itemless entries are identified by their category — it can't be cleared.
            raise ConflictError(
                TimelogEntity.WORKLOG,
                reason="an itemless worklog keeps a category — set another instead of clearing",
            )
        worklog.category_id = data.category_id
    await session.flush()
    await _emit(session, WorklogEvent.UPDATED, worklog, actor_id)
    return (await hydrate(session, [worklog], hpd))[0]


async def delete_worklog(
    session: AsyncSession, worklog: Worklog, actor_id: uuid.UUID
) -> None:
    await session.delete(worklog)
    await session.flush()
    await _emit(session, WorklogEvent.DELETED, worklog, actor_id)


# --- estimate + summary ---


async def set_estimate(
    session: AsyncSession, item_id: uuid.UUID, data: EstimateSet
) -> None:
    _, project = await _project_for_item(session, item_id)
    seconds = _parse(data.estimate, await _hours_per_day(session))
    estimate = await session.get(ItemEstimate, item_id)
    if estimate is None:
        session.add(ItemEstimate(item_id=item_id, original_estimate_seconds=seconds))
    else:
        estimate.original_estimate_seconds = seconds
    await session.flush()


async def clear_estimate(session: AsyncSession, item_id: uuid.UUID) -> None:
    await session.execute(delete(ItemEstimate).where(ItemEstimate.item_id == item_id))
    await session.flush()


async def has_estimate(session: AsyncSession, item_id: uuid.UUID) -> bool:
    """Whether the item has an item_estimates row — the workflow transition-guard
    seam (spec 61, require_estimate)."""
    return await session.get(ItemEstimate, item_id) is not None


async def item_summary(
    session: AsyncSession, item_id: uuid.UUID, project
) -> ItemTimeSummary:
    hpd = await _hours_per_day(session)
    estimate = await session.get(ItemEstimate, item_id)
    original = estimate.original_estimate_seconds if estimate else None
    logged = await logged_seconds(session, item_id)
    remaining = original - logged if original is not None else None
    entries = await hydrate(session, await worklogs_for_item(session, item_id), hpd)
    return ItemTimeSummary(
        item_id=item_id,
        enabled=await enablement.is_enabled(session, project.id),
        original_estimate_seconds=original,
        original_estimate=_fmt(original, hpd) if original is not None else None,
        logged_seconds=logged,
        logged=_fmt(logged, hpd),
        remaining_seconds=remaining,
        remaining=_fmt(remaining, hpd) if remaining is not None else None,
        entries=entries,
    )


async def _emit(
    session: AsyncSession,
    event_type: WorklogEvent,
    worklog: Worklog,
    actor_id: uuid.UUID,
    occurred_at: datetime | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=TimelogEntity.WORKLOG,
        entity_id=worklog.id,
        actor_id=actor_id,
        payload={
            # None for itemless (spec 59) entries — consumers already treat a
            # missing/None item_id as "no target item".
            "item_id": str(worklog.item_id) if worklog.item_id else None,
            "project_id": str(worklog.project_id) if worklog.project_id else None,
            "category_id": str(worklog.category_id) if worklog.category_id else None,
            "author_id": str(worklog.author_id),
            "worked_on": worklog.worked_on.isoformat(),
            "time_spent_seconds": worklog.time_spent_seconds,
        },
        occurred_at=occurred_at,
    )
