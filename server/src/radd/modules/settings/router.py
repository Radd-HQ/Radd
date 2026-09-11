import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import service
from .schemas import ResolvedSetting, ScopedSettingRead, ScopedSettingWrite
from .types import SettingKey, SettingScope

router = APIRouter(prefix="/scoped-settings", tags=["settings"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _authorize(
    session: AsyncSession, user, scope: SettingScope, scope_id: uuid.UUID | None
) -> None:
    """Gate a scope (specs 50/67): instance → instance admin, project →
    project.manage. Workspace scope no longer exists (spec 67)."""
    if scope is SettingScope.INSTANCE:
        if not authz.is_instance_admin(user):
            raise ForbiddenError("instance settings require an instance admin")
        return
    if scope_id is None:
        raise ConflictError("scoped_setting", reason=f"{scope.value} scope requires a scope_id")
    project = await projects_service.get_project(session, scope_id)
    await authz.require(session, user, Permission.PROJECT_MANAGE, project=project)


@router.get("/resolve", response_model=ResolvedSetting)
async def resolve_setting(
    key: SettingKey, session: Session, user: CurrentUser, project_id: uuid.UUID | None = None
) -> ResolvedSetting:
    """One key's effective value through the cascade (spec 70) — readable by any
    member (item.read on the project when given), unlike the manage-gated scope
    editors above. The SPA's `usePointsEnabled` gate reads this."""
    if project_id is not None:
        project = await projects_service.get_project(session, project_id)
        await authz.require(session, user, Permission.ITEM_READ, project=project)
    value = await service.resolve(session, key, project_id=project_id)
    return ResolvedSetting(key=key.value, value=value)


@router.get("", response_model=list[ScopedSettingRead])
async def list_scoped_settings(
    scope: SettingScope, session: Session, user: CurrentUser, scope_id: uuid.UUID | None = None
) -> list[ScopedSettingRead]:
    await _authorize(session, user, scope, scope_id)
    rows = await service.list_for_scope(session, scope, scope_id)
    return [ScopedSettingRead(**row) for row in rows]


@router.put("", response_model=ScopedSettingRead)
async def set_scoped_setting(
    data: ScopedSettingWrite, session: Session, user: CurrentUser
) -> ScopedSettingRead:
    await _authorize(session, user, data.scope, data.scope_id)
    await service.set_value(session, data.key, data.scope, data.scope_id, data.value)
    rows = await service.list_for_scope(session, data.scope, data.scope_id)
    return next(ScopedSettingRead(**row) for row in rows if row["key"] == data.key.value)


@router.delete("", status_code=204)
async def clear_scoped_setting(
    scope: SettingScope,
    key: SettingKey,
    session: Session,
    user: CurrentUser,
    scope_id: uuid.UUID | None = None,
) -> None:
    await _authorize(session, user, scope, scope_id)
    await service.clear_value(session, key, scope, scope_id)
