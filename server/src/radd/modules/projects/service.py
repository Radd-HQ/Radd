import uuid
from collections.abc import Iterable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.hooks import hooks
from radd.modules.events import service as events

from .models import Project
from .schemas import ProjectCreate, ProjectUpdate
from .types import ProjectEntity, ProjectEvent


async def create_project(
    session: AsyncSession, data: ProjectCreate, actor_id: uuid.UUID | None = None
) -> Project:
    key = data.key.upper()
    # Project keys are globally unique (Jira model) so an issue key `TD-1234` is an
    # unambiguous instance-wide address (see spec 21). Trade-off documented in the plan.
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
        payload={
            "key": project.key,
            "name": project.name,
            "description": project.description,
            "changes": changes,
        },
    )
    return project


async def list_projects(session: AsyncSession) -> list[Project]:
    return list((await session.execute(select(Project).order_by(Project.created_at))).scalars())


async def list_project_ids(session: AsyncSession) -> list[uuid.UUID]:
    """Authority resolution needs identities, not every project's content."""
    return list(await session.scalars(select(Project.id)))


async def project_ref(session: AsyncSession, project_id) -> dict | None:
    """The canonical `{id, key, name}` for a project inside an event payload
    (RADD-923). Registered as this plugin's `EntityRefSpec`, so every module that
    names a project as an event subject — and every auto-wired plugin entity that
    is project-scoped — gets the same three fields without writing them."""
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
    """Project by KEY (`TD`), case-insensitive. Keys are globally unique (the
    spec-21 Jira model), so this is an unambiguous instance-wide address — the
    one resolution every by-key surface shares (RADD-889 dedup of the MCP
    tools' per-handler copies)."""
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
