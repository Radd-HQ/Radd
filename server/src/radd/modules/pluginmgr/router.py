import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.kernel import entities as kentities
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.types import InstanceRole

from . import discovery, runtime, service
from .schemas import ContributionSettings, PluginCapabilityRead, PluginRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["plugins"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _require_admin(user: CurrentUser) -> None:
    if InstanceRole(user.instance_role) is not InstanceRole.ADMIN:
        raise ForbiddenError("plugin management requires an instance admin")


def _read(info: service.PluginInfo) -> PluginRead:
    return PluginRead(
        id=info.id, name=info.name, version=info.version, core=info.core,
        state=info.state.value, description=info.description, can_toggle=info.can_toggle,
        capabilities=[PluginCapabilityRead(**cap) for cap in info.capabilities],
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
    saved = await service.set_contribution_settings(session, plugin_id, body.disabled)
    return ContributionSettings(disabled=saved)


@router.post("/{plugin_id}/install", response_model=list[PluginRead])
async def install(plugin_id: str, session: Session, user: CurrentUser) -> list[PluginRead]:
    _require_admin(user)
    await service.install(session, plugin_id, actor_id=user.id)
    return [_read(i) for i in await service.list_plugins(session)]


@router.post("/{plugin_id}/enable", response_model=list[PluginRead])
async def enable(plugin_id: str, request: Request, session: Session, user: CurrentUser) -> list[PluginRead]:
    _require_admin(user)
    await service.enable(session, plugin_id, actor_id=user.id)
    # Hot-mount into the running app (no restart) — best effort; the state is the
    # source of truth and the next boot resolves it regardless.
    entry = discovery.installable_plugins().get(plugin_id) or discovery.core_plugins().get(plugin_id)
    if entry is not None:
        plugin, path = entry
        try:
            runtime.mount_plugin(request.app, plugin, path)
            # An entity plugin with no migration (e.g. an external plugin using create_all) needs
            # its tables created on runtime enable — idempotent, mirrors the boot lifespan step.
            if plugin.entities:
                await kentities.ensure_tables()
            # Mirror the boot lifespan: a hot-enabled plugin's startup hooks run
            # too (the ai plugin seeds its registry + starts the embedder here).
            for hook in plugin.on_startup:
                await hook()
        except Exception:  # a mount failure must not fail the state change…
            # …but it must not be INVISIBLE either — a silently-failed unmount
            # is how a "disabled" plugin kept serving (same class, enable side).
            logger.exception("hot-mount of %s failed; saved state applies on next boot", plugin_id)
    return [_read(i) for i in await service.list_plugins(session)]


@router.post("/{plugin_id}/disable", response_model=list[PluginRead])
async def disable(plugin_id: str, request: Request, session: Session, user: CurrentUser) -> list[PluginRead]:
    _require_admin(user)
    await service.disable(session, plugin_id, actor_id=user.id)
    entry = discovery.installable_plugins().get(plugin_id) or discovery.core_plugins().get(plugin_id)
    if entry is not None:
        plugin, path = entry
        # Shutdown hooks BEFORE unmount, mirroring the boot lifespan in reverse —
        # without this the ai plugin's embeddings dispatcher kept running after
        # a hot-disable.
        for hook in plugin.on_shutdown:
            try:
                await hook()
            except Exception:
                logger.exception("shutdown hook of %s failed during hot-disable", plugin_id)
        try:
            runtime.unmount_plugin(request.app, plugin, path)
        except Exception:
            logger.exception("hot-unmount of %s failed; saved state applies on next boot", plugin_id)
    return [_read(i) for i in await service.list_plugins(session)]


@router.post("/{plugin_id}/uninstall", response_model=list[PluginRead])
async def uninstall(plugin_id: str, request: Request, session: Session, user: CurrentUser) -> list[PluginRead]:
    _require_admin(user)
    entry = discovery.installable_plugins().get(plugin_id) or discovery.core_plugins().get(plugin_id)
    if entry is not None:
        plugin, path = entry
        for hook in plugin.on_shutdown:
            try:
                await hook()
            except Exception:
                logger.exception("shutdown hook of %s failed during uninstall", plugin_id)
        try:
            runtime.unmount_plugin(request.app, plugin, path)
        except Exception:
            logger.exception("hot-unmount of %s failed during uninstall", plugin_id)
    await service.uninstall(session, plugin_id, actor_id=user.id)
    return [_read(i) for i in await service.list_plugins(session)]
