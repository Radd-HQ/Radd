import uuid
from collections.abc import Iterable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .options import list_options as list_options
from .models import IssueType
from .schemas import IssueTypeCreate, IssueTypeUpdate
from .types import DEFAULT_TYPES, TypeEntity, TypeEvent


async def create_default_types(session: AsyncSession, project: Project) -> None:
    """Seed the default type set for a new project (project.created hook)."""
    for position, default in enumerate(DEFAULT_TYPES, start=1):
        issue_type = IssueType(
            project_id=project.id,
            name=default.name,
            color=default.color,
            icon=default.icon,
            position=position,
            is_default=default.is_default,
        )
        session.add(issue_type)
        await session.flush()
        await _emit(session, TypeEvent.CREATED, issue_type)


async def _clear_default(session: AsyncSession, project_id: uuid.UUID) -> None:
    await session.execute(
        update(IssueType).where(IssueType.project_id == project_id).values(is_default=False)
    )


async def create_type(
    session: AsyncSession, data: IssueTypeCreate, actor_id: uuid.UUID | None = None
) -> IssueType:
    project = await projects_service.get_project(session, data.project_id)
    if await session.scalar(
        select(IssueType.id).where(
            IssueType.project_id == project.id, IssueType.name == data.name
        )
    ):
        raise ConflictError(TypeEntity.ISSUE_TYPE, data.name)
    if data.position is None:
        max_position = await session.scalar(
            select(func.max(IssueType.position)).where(IssueType.project_id == project.id)
        )
        position = (max_position or 0) + 1
    else:
        position = data.position
    if data.is_default:
        await _clear_default(session, project.id)
    issue_type = IssueType(
        project_id=project.id,
        name=data.name,
        color=data.color,
        icon=data.icon,
        position=position,
        is_default=data.is_default,
        description_template=data.description_template or None,
    )
    session.add(issue_type)
    await session.flush()
    await _emit(session, TypeEvent.CREATED, issue_type, actor_id)
    return issue_type


async def update_type(
    session: AsyncSession,
    type_id: uuid.UUID,
    data: IssueTypeUpdate,
    actor_id: uuid.UUID | None = None,
) -> IssueType:
    issue_type = await get_type(session, type_id)
    project = await projects_service.get_project(session, issue_type.project_id)
    before = changes.snapshot(issue_type, TYPE_FIELDS)
    if data.name is not None:
        issue_type.name = data.name
    if data.color is not None:
        issue_type.color = data.color
    if data.icon is not None:
        issue_type.icon = data.icon
    if data.position is not None:
        issue_type.position = data.position
    if data.is_default:
        await _clear_default(session, project.id)
        issue_type.is_default = True
    # Template (spec 76): omitted = unchanged; explicit null/'' clears.
    if "description_template" in data.model_fields_set:
        issue_type.description_template = data.description_template or None
    await session.flush()
    await _emit(
        session,
        TypeEvent.UPDATED,
        issue_type,
        actor_id,
        changes.diff_object(issue_type, before, hidden=("description_template",)),
    )
    return issue_type


async def delete_type(
    session: AsyncSession, type_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    issue_type = await get_type(session, type_id)
    if issue_type.is_default:
        raise ConflictError(
            TypeEntity.ISSUE_TYPE, reason="cannot delete the default type; set another default first"
        )
    await projects_service.get_project(session, issue_type.project_id)
    await _emit(session, TypeEvent.DELETED, issue_type, actor_id)
    await session.delete(issue_type)  # items' type_id nulls via FK ondelete SET NULL
    await session.flush()


def ids_by_names(names: list[str]):
    """Select of issue-type ids matching these NAMES — the fragment seam for the
    items SLQ `type` builtin (RADD-888)."""
    return select(IssueType.id).where(IssueType.name.in_(names))


async def distinct_names(session: AsyncSession) -> list[str]:
    """Distinct type names instance-wide — SLQ value autocomplete + the NL
    repair vocabulary (was the one entity field with no value source)."""
    result = await session.execute(select(IssueType.name).distinct().order_by(IssueType.name))
    return list(result.scalars())


async def list_types(session: AsyncSession, project_id: uuid.UUID) -> list[IssueType]:
    result = await session.execute(
        select(IssueType).where(IssueType.project_id == project_id).order_by(IssueType.position)
    )
    return list(result.scalars())


async def get_type(session: AsyncSession, type_id: uuid.UUID) -> IssueType:
    issue_type = await session.get(IssueType, type_id)
    if issue_type is None:
        raise NotFoundError(TypeEntity.ISSUE_TYPE, type_id)
    return issue_type


async def default_type(session: AsyncSession, project_id: uuid.UUID) -> IssueType | None:
    return await session.scalar(
        select(IssueType).where(
            IssueType.project_id == project_id, IssueType.is_default.is_(True)
        )
    )


async def types_by_ids(
    session: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, IssueType]:
    id_set = {i for i in ids if i is not None}
    if not id_set:
        return {}
    result = await session.execute(select(IssueType).where(IssueType.id.in_(id_set)))
    return {t.id: t for t in result.scalars()}


#: What an issue-type edit can touch — the template records only "changed".
TYPE_FIELDS: tuple[str, ...] = (
    "name", "color", "icon", "position", "is_default", "description_template",
)


async def _emit(
    session: AsyncSession,
    event_type: TypeEvent,
    issue_type: IssueType,
    actor_id: uuid.UUID | None = None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=TypeEntity.ISSUE_TYPE,
        entity_id=issue_type.id,
        actor_id=actor_id,
        payload={"project_id": str(issue_type.project_id), "name": issue_type.name},
        subjects={"project": issue_type.project_id},
        changes=diff,
    )
