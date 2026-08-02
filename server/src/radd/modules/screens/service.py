import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.events import service as events
from radd.modules.fields import service as fields_service
from radd.modules.projects.models import Project

from .models import Screen, ScreenField
from .schemas import (
    EffectiveFieldRow,
    EffectiveScreen,
    ScreenFieldRow,
    ScreenRead,
)
from .types import (
    CUSTOM_FIELD_PREFIX,
    DEFAULT_BUILTIN_ORDER,
    ScreenBuiltinField,
    ScreenEntity,
    ScreenEvent,
    ScreenPlacement,
    default_placement,
    is_custom_field,
)

_VALID_BUILTINS = {field.value for field in ScreenBuiltinField}


def _validate_field(field: str) -> None:
    if is_custom_field(field):
        if not field[len(CUSTOM_FIELD_PREFIX) :]:
            raise ConflictError(ScreenEntity.SCREEN, reason="empty custom-field key")
        return
    if field not in _VALID_BUILTINS:
        raise ConflictError(ScreenEntity.SCREEN, reason=f"unknown screen field '{field}'")


async def _find_screen(
    session: AsyncSession, project_id: uuid.UUID, issue_type_id: uuid.UUID | None
) -> Screen | None:
    return await session.scalar(
        select(Screen).where(
            Screen.project_id == project_id,
            Screen.issue_type_id.is_(None)
            if issue_type_id is None
            else Screen.issue_type_id == issue_type_id,
        )
    )


async def get_screen_config(
    session: AsyncSession, project_id: uuid.UUID, issue_type_id: uuid.UUID | None
) -> ScreenRead:
    """A scope's stored screen (empty fields when none is configured)."""
    screen = await _find_screen(session, project_id, issue_type_id)
    rows = (
        [ScreenFieldRow(field=f.field, placement=ScreenPlacement(f.placement)) for f in screen.fields]
        if screen is not None
        else []
    )
    return ScreenRead(project_id=project_id, issue_type_id=issue_type_id, fields=rows)


async def replace_screen(
    session: AsyncSession,
    project: Project,
    issue_type_id: uuid.UUID | None,
    rows: Sequence[ScreenFieldRow],
    actor_id: uuid.UUID,
) -> ScreenRead:
    """Full-list replace of a scope's screen. Empty `rows` deletes the screen (the
    scope falls back to the project default, then the built-in defaults)."""
    for row in rows:
        _validate_field(row.field)
    seen: set[str] = set()
    for row in rows:
        if row.field in seen:
            raise ConflictError(ScreenEntity.SCREEN, reason=f"duplicate field '{row.field}'")
        seen.add(row.field)

    screen = await _find_screen(session, project.id, issue_type_id)
    if not rows:
        if screen is not None:
            await session.delete(screen)
            await session.flush()
        await _emit(session, project, issue_type_id, actor_id)
        return ScreenRead(project_id=project.id, issue_type_id=issue_type_id, fields=[])

    if screen is None:
        screen = Screen(
            project_id=project.id,
            issue_type_id=issue_type_id,
        )
        session.add(screen)
    screen.fields = [
        ScreenField(field=row.field, placement=row.placement.value, position=index)
        for index, row in enumerate(rows)
    ]
    await session.flush()
    await _emit(session, project, issue_type_id, actor_id)
    return ScreenRead(
        project_id=project.id,
        issue_type_id=issue_type_id,
        fields=[ScreenFieldRow(field=r.field, placement=ScreenPlacement(r.placement)) for r in screen.fields],
    )


async def resolve_effective(
    session: AsyncSession, project: Project, issue_type_id: uuid.UUID | None
) -> EffectiveScreen:
    """The merged, ordered placement of every arrangeable field for an item's
    (project, issue-type). Resolution: the issue-type's own screen, else the project
    default screen, else built-in defaults. Config placements/positions win; fields the
    config omits keep their default placement in canonical order (so a custom field added
    after the screen was saved still appears — collapsed — rather than vanishing)."""
    screen = None
    source = "default"
    if issue_type_id is not None:
        screen = await _find_screen(session, project.id, issue_type_id)
        if screen is not None:
            source = "issue_type"
    if screen is None:
        screen = await _find_screen(session, project.id, None)
        if screen is not None:
            source = "project"

    config = {f.field: (ScreenPlacement(f.placement), f.position) for f in screen.fields} if screen else {}

    definitions = await fields_service.definitions_for_project(session, project)
    universe: list[str] = [b.value for b in DEFAULT_BUILTIN_ORDER]
    universe += [f"{CUSTOM_FIELD_PREFIX}{d.key}" for d in definitions]

    ordered: list[tuple[int, int, str, ScreenPlacement]] = []
    for canonical_index, field in enumerate(universe):
        if field in config:
            placement, position = config[field]
            ordered.append((0, position, field, placement))  # configured fields sort first, by their position
        else:
            ordered.append((1, canonical_index, field, default_placement(field)))
    ordered.sort(key=lambda entry: (entry[0], entry[1]))

    return EffectiveScreen(
        project_id=project.id,
        issue_type_id=issue_type_id,
        source=source,
        fields=[
            EffectiveFieldRow(field=field, placement=placement, custom=is_custom_field(field))
            for _, _, field, placement in ordered
        ],
    )


async def _emit(
    session: AsyncSession, project: Project, issue_type_id: uuid.UUID | None, actor_id: uuid.UUID
) -> None:
    await events.emit(
        session,
        event_type=ScreenEvent.UPDATED,
        entity_type=ScreenEntity.SCREEN,
        entity_id=project.id,
        actor_id=actor_id,
        payload={
            "project_id": str(project.id),
            "issue_type_id": str(issue_type_id) if issue_type_id else None,
        },
    )
