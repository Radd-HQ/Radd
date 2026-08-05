import uuid
from collections.abc import Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .models import StateGroup, State, WorkflowTransition
from .schemas import StateCreate, StateGroupCreate, StateGroupUpdate, StateUpdate
from .types import DEFAULT_STATES, StateCategory, StateEntity, StateEvent


async def create_default_states(session: AsyncSession, project: Project) -> None:
    for position, default in enumerate(DEFAULT_STATES, start=1):
        state = State(
            project_id=project.id,
            name=default.name,
            category=default.category.value,
            position=position,
            is_default=default.is_default,
        )
        session.add(state)
        await session.flush()
        await _emit(session, StateEvent.CREATED, state)


async def create_state(
    session: AsyncSession, data: StateCreate, actor_id: uuid.UUID | None = None
) -> State:
    project = await projects_service.get_project(session, data.project_id)
    existing = await session.scalar(
        select(State.id).where(State.project_id == project.id, State.name == data.name)
    )
    if existing:
        raise ConflictError(StateEntity.STATE, data.name)
    if data.position is None:
        max_position = await session.scalar(
            select(func.max(State.position)).where(State.project_id == project.id)
        )
        position = (max_position or 0) + 1
    else:
        position = data.position
    state = State(
        project_id=project.id, name=data.name, category=data.category.value, position=position
    )
    session.add(state)
    await session.flush()
    await _emit(session, StateEvent.CREATED, state, actor_id)
    return state


async def update_state(
    session: AsyncSession, state_id: uuid.UUID, data: StateUpdate, actor_id: uuid.UUID | None = None
) -> State:
    state = await get_state(session, state_id)
    project = await projects_service.get_project(session, state.project_id)
    if data.name is not None:
        state.name = data.name
    if data.position is not None:
        state.position = data.position
    if "group_id" in data.model_fields_set:
        # RADD-852: null LEAVES the group (absent = untouched). Validate the
        # target exists so a stale picker 404s instead of writing a dangle.
        if data.group_id is not None:
            await get_state_group(session, data.group_id)
        state.group_id = data.group_id
    await session.flush()
    await _emit(session, StateEvent.UPDATED, state, actor_id)
    return state


async def delete_state(
    session: AsyncSession, state_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    """Delete a workflow state (spec 87 — the state.delete atom had no endpoint).

    Refused (409) while anything still points at it: the project's default state
    (every new item lands there), or any item currently sitting in it — move those
    first, since silently relocating someone's work is not a delete. Transitions
    mentioning the state are the workflow module's own rows and are cleaned up here.
    """
    state = await get_state(session, state_id)
    if state.is_default:
        raise ConflictError(
            StateEntity.STATE,
            reason=f"'{state.name}' is the project's default state — make another state default first",
        )
    # Deferred import: items loads after workflow (items.service imports this
    # module), so this is the tolerated backward edge — via a public service
    # function, never by reading the items tables.
    from radd.modules.items import service as items_service

    in_use = await items_service.count_items_in_state(session, state_id)
    if in_use:
        raise ConflictError(
            StateEntity.STATE,
            reason=f"{in_use} item(s) are still in '{state.name}' — move them to another state first",
        )
    await session.execute(
        delete(WorkflowTransition).where(
            (WorkflowTransition.from_state_id == state_id)
            | (WorkflowTransition.to_state_id == state_id)
        )
    )
    await _emit(session, StateEvent.DELETED, state, actor_id)
    await session.delete(state)
    await session.flush()


async def list_states(session: AsyncSession, project_id: uuid.UUID) -> list[State]:
    result = await session.execute(
        select(State).where(State.project_id == project_id).order_by(State.position)
    )
    return list(result.scalars())


async def states_for_projects(
    session: AsyncSession, project_ids: Iterable[uuid.UUID]
) -> list[State]:
    ids = list(project_ids)
    if not ids:
        return []
    result = await session.execute(
        select(State).where(State.project_id.in_(ids)).order_by(State.project_id, State.position)
    )
    return list(result.scalars())


async def get_state(session: AsyncSession, state_id: uuid.UUID) -> State:
    state = await session.get(State, state_id)
    if state is None:
        raise NotFoundError(StateEntity.STATE, state_id)
    return state


async def default_state(session: AsyncSession, project_id: uuid.UUID) -> State:
    state = await session.scalar(
        select(State).where(State.project_id == project_id, State.is_default.is_(True))
    )
    if state is None:
        raise NotFoundError(StateEntity.STATE, f"default for project {project_id}")
    return state


async def states_by_ids(
    session: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, State]:
    result = await session.execute(select(State).where(State.id.in_(set(ids))))
    return {s.id: s for s in result.scalars()}


async def state_ids_in_category(
    session: AsyncSession, project_id: uuid.UUID | None, category: StateCategory
) -> list[uuid.UUID]:
    query = select(State.id).where(State.category == category.value)
    if project_id:
        query = query.where(State.project_id == project_id)
    return list((await session.execute(query)).scalars())


async def _emit(
    session: AsyncSession,
    event_type: StateEvent,
    state: State,
    actor_id: uuid.UUID | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=StateEntity.STATE,
        entity_id=state.id,
        actor_id=actor_id,
        payload={"name": state.name, "category": state.category, "project_id": str(state.project_id)},
    )


# Re-export: the items-module enforcement seam (spec 61) — modules talk through
# public service functions, and items already imports workflow.service.
from .transitions import check_transition  # noqa: E402, F401


# --- state groups (RADD-852): the presentation tier ---------------------------


async def list_state_groups(session: AsyncSession) -> list[StateGroup]:
    result = await session.execute(select(StateGroup).order_by(StateGroup.position, StateGroup.name))
    return list(result.scalars())


async def get_state_group(session: AsyncSession, group_id: uuid.UUID) -> StateGroup:
    group = await session.get(StateGroup, group_id)
    if group is None:
        raise NotFoundError(StateEntity.STATE_GROUP, group_id)
    return group


async def create_state_group(session: AsyncSession, data: StateGroupCreate) -> StateGroup:
    existing = await session.scalar(select(StateGroup).where(StateGroup.name == data.name))
    if existing is not None:
        raise ConflictError(StateEntity.STATE_GROUP, reason=f"group '{data.name}' already exists")
    if data.position is None:
        max_position = await session.scalar(select(func.max(StateGroup.position)))
        position = (max_position or 0) + 1
    else:
        position = data.position
    group = StateGroup(name=data.name, color=data.color, position=position)
    session.add(group)
    await session.flush()
    return group


async def update_state_group(
    session: AsyncSession, group_id: uuid.UUID, data: StateGroupUpdate
) -> StateGroup:
    group = await get_state_group(session, group_id)
    if data.name is not None and data.name != group.name:
        clash = await session.scalar(select(StateGroup).where(StateGroup.name == data.name))
        if clash is not None:
            raise ConflictError(StateEntity.STATE_GROUP, reason=f"group '{data.name}' already exists")
        group.name = data.name
    if "color" in data.model_fields_set:
        group.color = data.color
    if data.position is not None:
        group.position = data.position
    await session.flush()
    return group


async def delete_state_group(session: AsyncSession, group_id: uuid.UUID) -> None:
    """Hard delete. `states.group_id` is SET NULL by the FK — members degrade
    to ungrouped; nothing semantic can break because the group never carried
    semantics (that was the whole design)."""
    group = await get_state_group(session, group_id)
    await session.delete(group)
    await session.flush()
