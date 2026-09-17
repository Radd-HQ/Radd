import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import service, store, live
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
        live_supported=info.live_supported, managed=info.managed,
    )


@router.get("", response_model=list[PluginRead])
async def list_plugins(session: Session, user: CurrentUser) -> list[PluginRead]:
    _require_admin(user)
    return [_read(i) for i in await service.list_plugins(session)]


@router.post("/packages/upload")
async def upload_package(request: Request, session: Session, user: CurrentUser) -> dict:
    _require_admin(user)
    # Raw wheel body: authenticate before reading, bound bytes as they arrive,
    # and avoid multipart's pre-authentication temporary-file spooling.
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > store.MAX_BYTES:
            raise HTTPException(status_code=413, detail="Package exceeds the 32 MiB upload limit")
        payload.extend(chunk)
    try:
        info = await asyncio.to_thread(store.install_wheel, bytes(payload))
    except (store.PackageError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await service.record_package_upload(session, info, user.id)
    return info


@router.get("/runtime")
async def runtime_status(user: CurrentUser) -> list[dict]:
    _require_admin(user)
    return live.reports()


@router.delete("/{plugin_id}/package")
async def remove_package(plugin_id: str, session: Session, user: CurrentUser) -> dict:
    _require_admin(user)
    # Forget in a separate committed request first. Never delete files while a
    # transaction could still roll back the requested state to enabled.
    if await service._row(session, plugin_id) is not None:
        raise HTTPException(status_code=409, detail="Disable, wait for all processes, then Forget before removing files")
    try:
        await asyncio.to_thread(store.remove, plugin_id)
    except (store.PackageError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await service.record_package_removal(session, plugin_id, user.id)
    return {"removed": plugin_id, "data_retained": True}


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
