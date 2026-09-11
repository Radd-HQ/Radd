import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.apitypes import TOTAL_COUNT_HEADER
from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import service
from .schemas import (
    FieldDefinitionCreate,
    FieldDefinitionRead,
    FieldDefinitionUpdate,
    FieldOptionRemove,
    FieldOptionsExtend,
    FieldWritabilityRead,
)

router = APIRouter(prefix="/fields", tags=["fields"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _to_read(field, restricted_ids: set[str], *, include_options: bool = True) -> FieldDefinitionRead:
    read = FieldDefinitionRead(**{
        name: (None if name == "options" and not include_options else getattr(field, name))
        for name in FieldDefinitionRead.model_fields if name != "restricted"
    })
    read.restricted = str(field.id) in restricted_ids
    return read


async def _require_manage_on_scope(
    session: AsyncSession,
    user,
    project_id: uuid.UUID | None,
    *,
    permission: authz.Permission = authz.Permission.FIELD_MANAGE,
) -> None:
    """`permission` on the field's scope: its project, or globally when unscoped.
    Spec 50: create/update/delete pass the granular field atom (field.manage still
    implies them); rule/grant reads keep the broad field.manage default."""
    if project_id is not None:
        project = await projects_service.get_project(session, project_id)
        await authz.require(session, user, permission, project=project)
    else:
        await authz.require(session, user, permission)


async def _require_manage_on_scopes(
    session: AsyncSession,
    user,
    project_ids: list[uuid.UUID],
    *,
    permission: authz.Permission = authz.Permission.FIELD_MANAGE,
) -> None:
    """A multi-project field's scope (spec 90 follow-up): require `permission` on
    EVERY project the field touches (a shared field needs authority over each), or
    globally when the field is global (no projects). A global grant satisfies all."""
    if not project_ids:
        await authz.require(session, user, permission)
        return
    for project_id in project_ids:
        await _require_manage_on_scope(session, user, project_id, permission=permission)


@router.post("", response_model=FieldDefinitionRead, status_code=201)
async def create_field(
    data: FieldDefinitionCreate, session: Session, user: CurrentUser
) -> FieldDefinitionRead:
    await _require_manage_on_scopes(
        session, user, data.project_ids, permission=authz.Permission.FIELD_CREATE
    )
    field = await service.create_field(session, data, actor_id=user.id)
    return _to_read(field, set())  # a new field has no grants yet


@router.patch("/{field_id}", response_model=FieldDefinitionRead)
async def update_field(
    field_id: uuid.UUID, data: FieldDefinitionUpdate, session: Session, user: CurrentUser,
    include_options: bool = True,
) -> FieldDefinitionRead:
    """Edit a field's presentation (spec 52) and scope (spec 90 follow-up)."""
    field = await service.get_field(session, field_id)
    # An empty scope means global authority, not an empty set of permissions.
    # Check both sides independently: a union loses the global requirement when
    # either the current or requested scope is empty.
    await _require_manage_on_scopes(
        session, user, field.project_ids, permission=authz.Permission.FIELD_UPDATE
    )
    if data.project_ids is not None:
        await _require_manage_on_scopes(
            session, user, data.project_ids, permission=authz.Permission.FIELD_UPDATE
        )
    updated = await service.update_field(session, field_id, data, actor_id=user.id)
    return _to_read(
        updated, await service.restricted_field_ids(session, ids=[str(field_id)]),
        include_options=include_options,
    )


@router.post("/{field_id}/options", response_model=FieldDefinitionRead)
async def add_field_options(
    field_id: uuid.UUID, data: FieldOptionsExtend, session: Session, user: CurrentUser,
    include_options: bool = True,
) -> FieldDefinitionRead:
    """ADD options to a select field — the spec-100 additive-only seam, exposed
    for the settings UI. Removal is its own route below, because it has to ask
    what happens to the items already holding the value."""
    field = await service.get_field(session, field_id)
    await _require_manage_on_scopes(
        session, user, field.project_ids, permission=authz.Permission.FIELD_UPDATE
    )
    await service.extend_options(session, field_id, data.values, actor_id=user.id)
    updated = await service.get_field(session, field_id)
    return _to_read(
        updated, await service.restricted_field_ids(session, ids=[str(field_id)]),
        include_options=include_options,
    )


@router.get("/{field_id}/options/usage", response_model=dict[str, int])
async def option_usage(
    field_id: uuid.UUID, value: str, session: Session, user: CurrentUser
) -> dict[str, int]:
    """How many items hold `value` — the dry run behind the removal dialog, so
    the question carries its own number (RADD-949)."""
    field = await service.get_field(session, field_id)
    await _require_manage_on_scopes(
        session, user, field.project_ids, permission=authz.Permission.FIELD_UPDATE
    )
    return {"items": await service.option_usage(session, field_id, value)}


@router.post("/{field_id}/options/remove", response_model=FieldDefinitionRead)
async def remove_field_option(
    field_id: uuid.UUID, data: FieldOptionRemove, session: Session, user: CurrentUser,
    include_options: bool = True,
) -> FieldDefinitionRead:
    """REMOVE one option, migrating the items that hold it (RADD-949).

    Declared AFTER `/{field_id}/options` but they do not collide — different
    paths, and both literal past the id. `replace_with` is only meaningful for a
    single select; see `service.remove_option` for which combinations are legal.
    """
    field = await service.get_field(session, field_id)
    await _require_manage_on_scopes(
        session, user, field.project_ids, permission=authz.Permission.FIELD_UPDATE
    )
    await service.remove_option(
        session,
        field_id,
        data.value,
        replace_with=data.replace_with,
        actor_id=user.id,
    )
    updated = await service.get_field(session, field_id)
    return _to_read(
        updated, await service.restricted_field_ids(session, ids=[str(field_id)]),
        include_options=include_options,
    )


@router.delete("/{field_id}", status_code=204)
async def delete_field(field_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    """Delete a custom-field definition and its grants (spec 87). Values already
    stored on items are keyed JSONB and are left in place, unrendered."""
    field = await service.get_field(session, field_id)
    await _require_manage_on_scopes(
        session, user, field.project_ids, permission=authz.Permission.FIELD_DELETE
    )
    await service.delete_field(session, field_id, actor_id=user.id)


@router.get("", response_model=list[FieldDefinitionRead])
async def list_fields(
    response: Response,
    session: Session,
    user: CurrentUser,
    q: str | None = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[FieldDefinitionRead]:
    # Global field managers need the definitions they manage even when they
    # cannot read issues. Other readers retain the existing issue-member floor.
    if (
        not await authz.holds(session, user, authz.Permission.FIELD_MANAGE)
        and not await authz.readable_projects(session, user)
    ):
        if limit is not None:
            response.headers[TOTAL_COUNT_HEADER] = "0"
        return []
    restricted_ids = await service.restricted_field_ids(session)
    fields = await service.list_fields(session, q=q, limit=limit, offset=offset)
    if limit is not None:
        response.headers[TOTAL_COUNT_HEADER] = str(await service.count_fields(session, q=q))
    return [_to_read(f, restricted_ids) for f in fields]


@router.get("/writable", response_model=FieldWritabilityRead)
async def field_writability(
    session: Session, user: CurrentUser, project_id: uuid.UUID
) -> FieldWritabilityRead:
    """Builtin names + custom keys the current user CAN'T write in `project_id` (spec 92 access
    resolution) — the SPA disables exactly those editors up front instead of erroring on save.
    Per-(actor, project), so it's cached per project and covers every item/board/list surface."""
    project = await projects_service.get_project(session, project_id)
    subjects = await authz.subjects_for(session, user, project)
    readonly = await service.readonly_field_keys(
        session,
        project,
        user_id=user.id,
        role_ids=subjects.role_ids,
        team_ids=subjects.team_ids,
        group_ids=subjects.group_ids,
        # RADD-816: instance admin, NOT project.manage — the bypass demotion.
        has_manage=await authz.is_admin(session, user),
    )
    return FieldWritabilityRead(readonly_fields=readonly)

# Builtin-field rules (spec 36) are now grants on resource_type="builtin_field"
# managed through the generic /grants API (spec 92) — no dedicated router.
