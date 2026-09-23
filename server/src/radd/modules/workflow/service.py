import uuid
from collections.abc import Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .options import list_options as list_options
from .models import State, StateCategoryDef, WorkflowTransition
from .schemas import StateCategoryCreate, StateCategoryUpdate, StateCreate, StateUpdate
from .types import DEFAULT_STATES, StateCategory, StateEntity, StateEvent


async def create_default_states(session: AsyncSession, project: Project) -> None:
    for position, default in enumerate(DEFAULT_STATES, start=1):
        state = State(
            project_id=project.id,
            name=default.name,
            category=default.category.value,
            category_key=default.category.value,  # builtin rows share the enum keys
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
    row = await get_state_category(session, data.category)
    state = State(
        project_id=project.id,
        name=data.name,
        # RADD-854: the semantic column DERIVES from the vocabulary row.
        category=row.behaves_as,
        category_key=row.key,
        position=position,
    )
    session.add(state)
    await session.flush()
    await _emit(session, StateEvent.CREATED, state, actor_id)
    return state


async def update_state(
    session: AsyncSession, state_id: uuid.UUID, data: StateUpdate, actor_id: uuid.UUID | None = None
) -> State:
    state = await get_state(session, state_id)
    await projects_service.get_project(session, state.project_id)
    before = changes.snapshot(state, ("name", "position", "category_key"))
    if data.name is not None:
        state.name = data.name
    if data.position is not None:
        state.position = data.position
    if data.category is not None:
        # RADD-853/854: re-classifying sets the vocabulary row AND derives the
        # semantic column from its behaves_as — every category consumer reads
        # the new behaviour from this moment on (the admin's call).
        row = await get_state_category(session, data.category)
        state.category = row.behaves_as
        state.category_key = row.key
    await session.flush()
    await _emit(session, StateEvent.UPDATED, state, actor_id, changes.diff_object(state, before))
    return state


async def delete_state(
    session: AsyncSession,
    state_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    *,
    reassign_to: uuid.UUID | None = None,
    actor=None,
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

    if reassign_to is not None:
        # RADD-853 (the spec-89 delete-with-successor precedent): items move
        # to the named successor first, through the items seam that emits per
        # item. Same project only; the state itself is not a successor.
        successor = await get_state(session, reassign_to)
        if successor.id == state.id:
            raise ConflictError(StateEntity.STATE, reason="a state cannot be its own successor")
        if successor.project_id != state.project_id:
            raise ConflictError(
                StateEntity.STATE, reason="the successor must belong to the same project"
            )
        if actor is not None:
            await items_service.reassign_state(session, state.id, successor.id, actor)
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
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=StateEntity.STATE,
        entity_id=state.id,
        actor_id=actor_id,
        payload={"name": state.name, "category": state.category, "project_id": str(state.project_id)},
        subjects={"project": state.project_id},
        changes=diff,
    )


# Re-export: the items-module enforcement seam (spec 61) — modules talk through
# public service functions, and items already imports workflow.service.
from .transitions import check_transition, release_transitions  # noqa: E402, F401




# --- state categories (RADD-854): the user-owned vocabulary tier -------------


def _slug(name: str) -> str:
    """A stable key minted from the name at CREATE time — immutable after (it
    is the reference states carry), so a later rename never rewrites states."""
    import re as _re

    key = _re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return key[:60] or "category"


async def list_state_categories(session: AsyncSession) -> list[StateCategoryDef]:
    result = await session.execute(
        select(StateCategoryDef).order_by(StateCategoryDef.position, StateCategoryDef.name)
    )
    return list(result.scalars())


async def get_state_category(session: AsyncSession, key_or_id) -> StateCategoryDef:
    """By KEY (the reference states carry) or by row id (the admin routes)."""
    row = await session.scalar(
        select(StateCategoryDef).where(StateCategoryDef.key == str(key_or_id))
    )
    if row is None:
        try:
            row = await session.get(StateCategoryDef, uuid.UUID(str(key_or_id)))
        except (ValueError, TypeError):
            row = None
    if row is None:
        raise NotFoundError(StateEntity.STATE_CATEGORY, key_or_id)
    return row


async def create_state_category(
    session: AsyncSession, data: StateCategoryCreate
) -> StateCategoryDef:
    key = _slug(data.name)
    clash = await session.scalar(
        select(StateCategoryDef).where(
            (StateCategoryDef.key == key) | (StateCategoryDef.name == data.name)
        )
    )
    if clash is not None:
        raise ConflictError(
            StateEntity.STATE_CATEGORY, reason=f"category '{data.name}' already exists"
        )
    if data.position is None:
        max_position = await session.scalar(select(func.max(StateCategoryDef.position)))
        position = (max_position or 0) + 1
    else:
        position = data.position
    row = StateCategoryDef(
        key=key,
        name=data.name,
        color=data.color,
        position=position,
        behaves_as=data.behaves_as.value,
        is_builtin=False,
    )
    session.add(row)
    await session.flush()
    return row


async def update_state_category(
    session: AsyncSession,
    category_id: uuid.UUID,
    data: StateCategoryUpdate,
    *,
    actor_id: uuid.UUID | None = None,
) -> StateCategoryDef:
    row = await get_state_category(session, category_id)
    before = changes.snapshot(row, ("name", "behaves_as", "color", "position"))
    if data.name is not None and data.name != row.name:
        clash = await session.scalar(
            select(StateCategoryDef).where(StateCategoryDef.name == data.name)
        )
        if clash is not None:
            raise ConflictError(
                StateEntity.STATE_CATEGORY, reason=f"category '{data.name}' already exists"
            )
        row.name = data.name
    if data.behaves_as is not None and data.behaves_as.value != row.behaves_as:
        if row.is_builtin:
            raise ConflictError(
                StateEntity.STATE_CATEGORY,
                reason=f"'{row.name}' is a builtin — its behaviour is its identity",
            )
        # The RIPPLE: every state classified under this row re-derives its
        # semantic column in one UPDATE — reports change meaning from here on.
        row.behaves_as = data.behaves_as.value
        await session.execute(
            State.__table__.update()
            .where(State.__table__.c.category_key == row.key)
            .values(category=row.behaves_as)
        )
    if "color" in data.model_fields_set:
        row.color = data.color
    if data.position is not None:
        row.position = data.position
    await session.flush()
    # Spec 123: re-classifying a category changes what every report means —
    # it used to leave no event at all.
    diff = changes.diff_object(row, before)
    if diff:
        await events.emit(
            session,
            event_type=StateEvent.CATEGORY_UPDATED,
            entity_type=StateEntity.STATE_CATEGORY,
            entity_id=row.id,
            actor_id=actor_id,
            payload={"key": row.key, "name": row.name},
            changes=diff,
        )
    return row


async def delete_state_category(session: AsyncSession, category_id: uuid.UUID) -> None:
    """Custom rows only, and only while no state references them — a category
    with states has meaning in flight, and silently re-homing states is not a
    delete (the spec-87 states rule, one tier up)."""
    row = await get_state_category(session, category_id)
    if row.is_builtin:
        raise ConflictError(
            StateEntity.STATE_CATEGORY, reason=f"'{row.name}' is a builtin category"
        )
    in_use = await session.scalar(
        select(func.count()).select_from(State).where(State.category_key == row.key)
    )
    if in_use:
        raise ConflictError(
            StateEntity.STATE_CATEGORY,
            reason=f"{in_use} state(s) are classified as '{row.name}' — re-categorise them first",
        )
    await session.delete(row)
    await session.flush()
