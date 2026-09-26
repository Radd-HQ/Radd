import uuid
from collections.abc import Iterable

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.hooks import hooks
from radd.kernel import registries
from radd.modules.events import service as events

from .models import Project
from .schemas import ProjectCreate, ProjectUpdate
from .types import (
    ProjectDeleting,
    ProjectEntity,
    ProjectEvent,
    ProjectHook,
    ProjectInspection,
)


async def create_project(
    session: AsyncSession, data: ProjectCreate, actor_id: uuid.UUID | None = None
) -> Project:
    key = data.key.upper()
    existing = await session.scalar(select(Project.id).where(Project.key == key))
    if existing:
        raise ConflictError(ProjectEntity.PROJECT, key)
    project = Project(key=key, name=data.name)
    session.add(project)
    await session.flush()
    await events.emit(
        session,
        event_type=ProjectEvent.PROJECT_CREATED,
        entity_type=ProjectEntity.PROJECT,
        entity_id=project.id,
        actor_id=actor_id,
        payload={"key": project.key, "name": project.name},
    )
    await hooks.dispatch(session, ProjectEvent.PROJECT_CREATED, project)
    return project


async def update_project(
    session: AsyncSession, project: Project, data: ProjectUpdate, actor_id: uuid.UUID | None = None
) -> Project:
    """Rename / describe a project (RADD-1009). The key is not a field of
    `ProjectUpdate` on purpose — see its docstring. A no-op PATCH (nothing set,
    or every value already current) emits nothing: an event that says
    "updated" with an empty diff is noise to every consumer downstream."""
    changes: list[dict[str, str]] = []
    for field in ("name", "description"):
        if field not in data.model_fields_set:
            continue
        new = getattr(data, field)
        if new is None:
            continue
        old = getattr(project, field)
        if new == old:
            continue
        setattr(project, field, new)
        changes.append({"field": field, "from": old, "to": new})
    if not changes:
        return project
    await session.flush()
    await events.emit(
        session,
        event_type=ProjectEvent.PROJECT_UPDATED,
        entity_type=ProjectEntity.PROJECT,
        entity_id=project.id,
        actor_id=actor_id,
        payload={"key": project.key, "name": project.name, "description": project.description},
        changes=changes,
    )
    return project


async def list_projects(session: AsyncSession) -> list[Project]:
    return list((await session.execute(select(Project).order_by(Project.created_at))).scalars())


async def list_project_ids(session: AsyncSession) -> list[uuid.UUID]:
    """Authority resolution needs identities, not every project's content."""
    return list(await session.scalars(select(Project.id)))


async def project_ref(session: AsyncSession, project_id) -> dict | None:
    """The canonical `{id, key, name}` event-payload ref (RADD-923; this plugin's `EntityRefSpec`)."""
    project = await session.get(Project, project_id)
    if project is None:
        return None
    return {"id": str(project.id), "key": project.key, "name": project.name}


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError(ProjectEntity.PROJECT, project_id)
    return project


async def get_by_key(session: AsyncSession, key: str) -> Project:
    """Project by KEY, case-insensitive — the one by-key resolution (keys are instance-unique)."""
    project = await session.scalar(select(Project).where(Project.key == key.upper()))
    if project is None:
        raise NotFoundError(ProjectEntity.PROJECT, key)
    return project


async def project_keys(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = await session.execute(select(Project.id, Project.key).where(Project.id.in_(set(ids))))
    return dict(rows.all())


async def project_exists(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """Is this a real project — asked by callers validating a REFERENCE (a role
    grant's scope), which want a boolean, not the row and not an exception."""
    return await session.scalar(select(Project.id).where(Project.id == project_id)) is not None


async def allocate_item_number(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Atomically claim the next item number for a project (safe under concurrency)."""
    result = await session.execute(
        update(Project)
        .where(Project.id == project_id)
        .values(next_number=Project.next_number + 1)
        .returning(Project.next_number)
    )
    next_number = result.scalar_one_or_none()
    if next_number is None:
        raise NotFoundError(ProjectEntity.PROJECT, project_id)
    return next_number - 1


async def reserve_item_number(session: AsyncSession, project_id: uuid.UUID, number: int) -> None:
    """Advance a project's counter past an explicitly-claimed number (import path),
    so future auto-numbering won't collide. Never moves the counter backward."""
    await session.execute(
        update(Project)
        .where(Project.id == project_id, Project.next_number <= number)
        .values(next_number=number + 1)
    )


# --- deletion (RADD-1174) ------------------------------------------------------


async def inspect_project(session: AsyncSession, project: Project) -> ProjectInspection:
    """What deleting this project would destroy, and what forbids it; each owner
    writes its own line via `ProjectHook.INSPECTING`. The same object drives the
    confirmation dialog and `delete_project`'s refusal."""
    inspection = ProjectInspection(project=project)
    await hooks.dispatch(session, ProjectHook.INSPECTING, inspection)
    return inspection


async def delete_project(
    session: AsyncSession, project: Project, *, actor_id: uuid.UUID | None = None
) -> ProjectInspection:
    """HARD-delete a project and everything in it (RADD-1174), inside the caller's
    transaction so a refusal leaves nothing half-deleted:
    1. `inspect_project` — a blocker (mail still routed here) is a 409: a mail
       source with no default project would bounce every message;
    2. `ProjectHook.DELETING` — owners remove what the DB cannot cascade
       (polymorphic children, grants, scoped settings, and fields/link types
       scoped ONLY here, which would otherwise turn global);
    3. the `ProjectPurgeSpec` tables in FK order, then the row.
    The event is emitted first so its subject ref still resolves. Returns the
    inspection."""
    inspection = await inspect_project(session, project)
    if inspection.blockers:
        named = "; ".join(
            f"{b.label}" + (f" ({b.hint})" if b.hint else "") for b in inspection.blockers
        )
        raise ConflictError(
            ProjectEntity.PROJECT,
            reason=f"{project.key} cannot be deleted while something still routes to it — {named}",
        )
    await events.emit(
        session,
        event_type=ProjectEvent.PROJECT_DELETED,
        entity_type=ProjectEntity.PROJECT,
        entity_id=project.id,
        actor_id=actor_id,
        payload={"key": project.key, "name": project.name, "removed": dict(inspection.counts)},
    )
    await hooks.dispatch(session, ProjectHook.DELETING, ProjectDeleting(project, actor_id))
    await purge_project_rows(session, project.id)
    await session.delete(project)
    await session.flush()
    return inspection


async def purge_project_rows(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Delete every `ProjectPurgeSpec` table's rows in FK-safe order. Plain DELETEs:
    per-row services would re-check permissions and emit events for work that never happened."""
    for table in registries.project_purge_tables():
        await session.execute(
            text(f"DELETE FROM {table} WHERE project_id = :id"), {"id": project_id}
        )
