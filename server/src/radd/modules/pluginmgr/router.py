from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import service
from .schemas import ContributionSettings, PluginCapabilityRead, PluginRead

router = APIRouter(prefix="/plugins", tags=["plugins"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _require_admin(user: CurrentUser) -> None:
    if not authz.is_instance_admin(user):
        raise ForbiddenError("plugin management requires an instance admin")


def _read(info: service.PluginInfo) -> PluginRead:
    return PluginRead(
        id=info.id, name=info.name, version=info.version, core=info.core,
        state=info.state.value, description=info.description, can_toggle=info.can_toggle,
        capabilities=[PluginCapabilityRead(**cap) for cap in info.capabilities],
        active=info.active, restart_required=info.restart_required,
        origin=info.origin, dependencies=list(info.dependencies), problems=list(info.problems),
    )


@router.get("", response_model=list[PluginRead])
async def list_plugins(session: Session, user: CurrentUser) -> list[PluginRead]:
    _require_admin(user)
    return [_read(i) for i in await service.list_plugins(session)]


@router.get("/contribution-settings", response_model=ContributionSettings)
async def get_contribution_settings(session: Session, user: CurrentUser) -> ContributionSettings:
    """Every instance-wide-disabled UI contribution (spec 94), `"<name>::<slot>::<id>"` keys. Any
    signed-in user reads this — the SPA needs it to hide globally-disabled pieces for everyone."""
    return ContributionSettings(disabled=await service.contribution_settings_all(session))


@router.put("/{plugin_id}/contribution-settings", response_model=ContributionSettings)
async def set_contribution_settings(
    plugin_id: str, body: ContributionSettings, session: Session, user: CurrentUser
) -> ContributionSettings:
    """Replace a plugin's instance-wide-disabled set (`"<slot>::<id>"` keys). Admin only."""
    _require_admin(user)
    saved = await service.set_contribution_settings(
        session, plugin_id, body.disabled, actor_id=user.id
    )
    return ContributionSettings(disabled=saved)


@router.post("/{plugin_id}/install", response_model=list[PluginRead])
async def install(plugin_id: str, session: Session, user: CurrentUser) -> list[PluginRead]:
    _require_admin(user)
    await service.install(session, plugin_id, actor_id=user.id)
    return [_read(i) for i in await service.list_plugins(session)]


@router.post("/{plugin_id}/enable", response_model=list[PluginRead])
async def enable(plugin_id: str, session: Session, user: CurrentUser) -> list[PluginRead]:
    _require_admin(user)
    await service.enable(session, plugin_id, actor_id=user.id)
    return [_read(i) for i in await service.list_plugins(session)]


@router.post("/{plugin_id}/disable", response_model=list[PluginRead])
async def disable(plugin_id: str, session: Session, user: CurrentUser) -> list[PluginRead]:
    _require_admin(user)
    await service.disable(session, plugin_id, actor_id=user.id)
    return [_read(i) for i in await service.list_plugins(session)]


@router.post("/{plugin_id}/uninstall", response_model=list[PluginRead])
async def uninstall(plugin_id: str, session: Session, user: CurrentUser) -> list[PluginRead]:
    _require_admin(user)
    await service.uninstall(session, plugin_id, actor_id=user.id)
    return [_read(i) for i in await service.list_plugins(session)]
