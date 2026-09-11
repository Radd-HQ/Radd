"""The plugin manager service — the lifecycle state machine (docs/plugin-platform.md §10).

Core plugins (`config.modules`) are always ENABLED and cannot be disabled/uninstalled.
Non-core plugins carry a row in `installed_plugins`; absent a row they are DISCOVERED.
Enable/disable flip the state (the running app mounts/unmounts accordingly + the next
boot resolves the enabled set); install/uninstall are the heavy migration steps.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import capabilities as kcaps
from radd.modules.events import service as events

from . import discovery
from .models import InstalledPlugin
from .types import PluginOrigin, PluginEntity, PluginEvent, PluginState


@dataclass(frozen=True)
class PluginInfo:
    id: str
    name: str  # the stable enable-key / UI slot-registry tag (may differ from the dotted id)
    version: str
    core: bool
    state: PluginState
    description: str
    can_toggle: bool  # non-core only
    # The plugin's evaluated CapabilitySpecs ({key,label,category,enabled}) —
    # evaluated from the plugin OBJECT, not the kernel registry, so a disabled
    # connector still reports whether its env config is present (the Plugins
    # page is the home for per-connector status; settings reorg).
    capabilities: tuple[dict, ...] = ()


def _capabilities(plugin) -> tuple[dict, ...]:
    return tuple(
        {key: desc[key] for key in ("key", "label", "category", "enabled")}
        for desc in (kcaps.describe(cap) for cap in plugin.capabilities)
    )


async def _row(session: AsyncSession, plugin_id: str) -> InstalledPlugin | None:
    return await session.get(InstalledPlugin, plugin_id)


async def _states(session: AsyncSession) -> dict[str, InstalledPlugin]:
    rows = (await session.execute(select(InstalledPlugin))).scalars()
    return {r.id: r for r in rows}


async def list_plugins(session: AsyncSession) -> list[PluginInfo]:
    """Every plugin the manager knows, with its lifecycle state.

    Core bootstrap plugins (config.modules, core=True) are locked-ENABLED. Optional
    bootstrap plugins (config.modules, core=False) are ENABLED unless a DISABLED row
    exists — they're on by default, disableable. Installable plugins carry their row
    state (DISCOVERED until installed)."""
    rows = await _states(session)
    infos: list[PluginInfo] = []
    for plugin_id, (plugin, _path) in discovery.core_plugins().items():
        row = rows.get(plugin_id)
        if plugin.core:
            state, toggle = PluginState.ENABLED, False
        else:
            disabled = row is not None and row.state == PluginState.DISABLED.value
            state, toggle = (PluginState.DISABLED if disabled else PluginState.ENABLED), True
        infos.append(PluginInfo(plugin_id, plugin.name, plugin.version, plugin.core, state,
                                plugin.description, can_toggle=toggle,
                                capabilities=_capabilities(plugin)))
    for plugin_id, (plugin, _path) in discovery.installable_plugins().items():
        row = rows.get(plugin_id)
        state = PluginState(row.state) if row else PluginState.DISCOVERED
        infos.append(PluginInfo(plugin_id, plugin.name, plugin.version, False, state,
                                plugin.description, can_toggle=True,
                                capabilities=_capabilities(plugin)))
    infos.sort(key=lambda i: (i.core, i.id))
    return infos


def _resolve_toggleable(plugin_id: str):
    """Return (plugin, path, kind) for a NON-core plugin the admin may toggle —
    whether it's an optional bootstrap plugin or an installable one. Core → 409,
    unknown → 404."""
    core = discovery.core_plugins().get(plugin_id)
    if core is not None:
        plugin, path = core
        if plugin.core:
            raise ConflictError(
                PluginEntity.PLUGIN, reason=f"{plugin_id} is a core plugin — always enabled"
            )
        return plugin, path, PluginOrigin.BOOTSTRAP.value
    inst = discovery.installable_plugins().get(plugin_id)
    if inst is not None:
        return inst[0], inst[1], PluginOrigin.INSTALLABLE.value
    raise NotFoundError(PluginEntity.PLUGIN, plugin_id)


def _ensure_no_dependents(plugin) -> None:
    """Block disabling a plugin another currently-loaded plugin depends on (§10)."""
    from radd.kernel import registries

    dependents = sorted(
        p.id for p in registries.plugins.values()
        if plugin.name in p.depends_on and p.id != plugin.id
    )
    if dependents:
        raise ConflictError(
            PluginEntity.PLUGIN,
            reason=f"{plugin.id} is required by {', '.join(dependents)} — disable those first",
        )


async def _emit(session: AsyncSession, event: PluginEvent, plugin_id: str, actor_id) -> None:
    await events.emit(session, event_type=event, entity_type=PluginEntity.PLUGIN,
                      entity_id=plugin_id, actor_id=actor_id, payload={"id": plugin_id})


async def _upsert(session: AsyncSession, plugin, state: PluginState) -> InstalledPlugin:
    row = await _row(session, plugin.id)
    if row is None:
        row = InstalledPlugin(id=plugin.id, version=plugin.version, state=state.value, config={})
        session.add(row)
    else:
        row.state = state.value
    await session.flush()
    return row


async def install(session: AsyncSession, plugin_id: str, actor_id: uuid.UUID | None = None) -> InstalledPlugin:
    plugin, _path, kind = _resolve_toggleable(plugin_id)
    if kind == PluginOrigin.BOOTSTRAP.value:  # ships in the main migration chain — install ⇒ ensure enabled
        return await enable(session, plugin_id, actor_id)
    row = await _row(session, plugin_id)
    if row is None:
        row = InstalledPlugin(id=plugin_id, version=plugin.version, state=PluginState.INSTALLED.value, config={})
        session.add(row)
    elif row.state == PluginState.ERRORED.value:
        # Re-installing a quarantined plugin clears the error back to INSTALLED. (There is no
        # UNINSTALLED row state — uninstall DELETES the row — so an existing row otherwise means the
        # plugin is already installed/enabled/disabled and install is a no-op.)
        row.state = PluginState.INSTALLED.value
    await session.flush()
    await _emit(session, PluginEvent.INSTALLED, plugin_id, actor_id)
    return row


async def enable(session: AsyncSession, plugin_id: str, actor_id: uuid.UUID | None = None) -> InstalledPlugin:
    plugin, _path, _kind = _resolve_toggleable(plugin_id)
    row = await _upsert(session, plugin, PluginState.ENABLED)
    await _emit(session, PluginEvent.ENABLED, plugin_id, actor_id)
    return row


async def disable(session: AsyncSession, plugin_id: str, actor_id: uuid.UUID | None = None) -> InstalledPlugin:
    plugin, _path, kind = _resolve_toggleable(plugin_id)
    _ensure_no_dependents(plugin)
    row = await _row(session, plugin_id)
    # An installable plugin must actually be enabled to disable; an optional bootstrap
    # plugin is enabled-by-default (no row), so disabling writes a DISABLED row.
    if kind == PluginOrigin.INSTALLABLE.value and (row is None or row.state != PluginState.ENABLED.value):
        raise ConflictError(PluginEntity.PLUGIN, reason=f"{plugin_id} is not enabled")
    row = await _upsert(session, plugin, PluginState.DISABLED)
    await _emit(session, PluginEvent.DISABLED, plugin_id, actor_id)
    return row


# --- instance-wide contribution settings (spec 94) --------------------------------------------
# A plugin's UI contributions can be disabled INSTANCE-WIDE by an admin (distinct from a user
# disabling one for just themselves via /auth/me/preferences). The set lives in the plugin's own
# `InstalledPlugin.config['disabled_contributions']` as `"<slot>::<id>"` keys, so it's plugin-scoped
# and drops when the plugin is uninstalled. The aggregate read prefixes each with the plugin's
# `name` (the UI slot-registry tag), the exact `"<name>::<slot>::<id>"` key the SDK matches on.
_DISABLED_KEY = "disabled_contributions"


async def contribution_settings_all(session: AsyncSession) -> list[str]:
    """Every instance-wide-disabled contribution across all plugins, as `"<name>::<slot>::<id>"`
    keys — what the SPA loads to hide globally-disabled pieces for everyone."""
    known = discovery.all_known()
    rows = (await session.execute(select(InstalledPlugin))).scalars().all()
    out: list[str] = []
    for row in rows:
        entry = known.get(row.id)
        if entry is None:
            continue
        name = entry[0].name
        for slot_id in (row.config or {}).get(_DISABLED_KEY, []):
            out.append(f"{name}::{slot_id}")
    return out


async def set_contribution_settings(
    session: AsyncSession, plugin_id: str, disabled: list[str]
) -> list[str]:
    """Replace a plugin's instance-wide-disabled set (`"<slot>::<id>"` keys). Get-or-creates the
    plugin's row WITHOUT changing its lifecycle: a new row is seeded with the plugin's DEFAULT
    reported state (core/bootstrap-optional → ENABLED, installable → DISCOVERED), so persisting a
    contribution setting never accidentally enables or disables the plugin itself. In practice the
    row already exists and is ENABLED — you only manage a plugin's contributions once its UI loads."""
    entry = discovery.all_known().get(plugin_id)
    if entry is None:
        raise NotFoundError(PluginEntity.PLUGIN, plugin_id)
    plugin, _path = entry
    row = await _row(session, plugin_id)
    if row is None:
        # config.modules plugins (core + optional bootstrap) are on-by-default; installable ones are
        # DISCOVERED until installed. Match that so the created row reports the same state as none.
        default = (
            PluginState.ENABLED
            if plugin_id in discovery.core_plugins()
            else PluginState.DISCOVERED
        )
        row = InstalledPlugin(
            id=plugin_id, version=plugin.version, state=default.value, config={}
        )
        session.add(row)
    # Reassign (not mutate) so SQLAlchemy flags the JSON column dirty.
    row.config = {**(row.config or {}), _DISABLED_KEY: list(disabled)}
    await session.flush()
    return list(disabled)


async def sweep_plugin_atoms(session: AsyncSession, plugin, actor_id: uuid.UUID | None) -> dict:
    """RADD-818: strip a departing plugin's atoms from stored roles and token
    scopes, and delete the grants of its access-resource types — the RADD-701
    migration pattern applied at runtime, each step over its own table.

    Only atoms the plugin itself DECLARED are stripped (its PermissionSpec keys
    and its CRUD resources' key.action forms) — never a shared umbrella like
    global.manage. Relation-qualified forms (`x.read@own`) strip by BASE. The
    emitted payload names everything removed, because silently narrowing a
    role is exactly what an access review needs to see."""
    import json

    from sqlalchemy import text as sa_text

    from radd.modules.access import service as access_service
    from radd.modules.auth.types import split_permission

    declared = {p.key for p in plugin.permissions}
    for crud in plugin.crud_resources:
        declared |= {f"{crud.key}.{action}" for action in crud.actions}
    resource_types = [
        getattr(ar, "resource_type") for ar in getattr(plugin, "access_resources", ())
    ]

    def _strip(atoms: list) -> list:
        return [a for a in atoms if split_permission(str(a))[0] not in declared]

    swept_roles: list[str] = []
    if declared:
        for role_id, key, permissions in (
            await session.execute(sa_text("SELECT id, key, permissions FROM roles"))
        ).fetchall():
            atoms = permissions if isinstance(permissions, list) else json.loads(permissions)
            stripped = _strip(atoms)
            if stripped != list(atoms):
                await session.execute(
                    sa_text("UPDATE roles SET permissions = :perms WHERE id = :id"),
                    {"perms": json.dumps(stripped), "id": role_id},
                )
                swept_roles.append(key)
        for token_id, scopes in (
            await session.execute(
                sa_text("SELECT id, scopes FROM api_tokens WHERE scopes IS NOT NULL")
            )
        ).fetchall():
            # Older writers stored JSON null, which passes SQL IS NOT NULL.
            # It represents an unscoped credential, with no atoms to remove.
            if scopes is None:
                continue
            data = scopes if isinstance(scopes, dict) else json.loads(scopes)
            if data is None:
                continue
            changed = False
            if isinstance(data.get("global"), list):
                stripped = _strip(data["global"])
                changed |= stripped != data["global"]
                data["global"] = stripped
            for pid, atoms in (data.get("projects") or {}).items():
                stripped = _strip(atoms)
                changed |= stripped != atoms
                data["projects"][pid] = stripped
            if changed:
                await session.execute(
                    sa_text("UPDATE api_tokens SET scopes = :scopes WHERE id = :id"),
                    {"scopes": json.dumps(data), "id": token_id},
                )
    dropped_grants = await access_service.clear_resource_types(session, resource_types)
    summary = {
        "stripped_atoms": sorted(declared),
        "swept_roles": swept_roles,
        "dropped_grant_types": resource_types,
        "dropped_grants": dropped_grants,
    }
    await events.emit(
        session,
        event_type=PluginEvent.UNINSTALLED,
        entity_type=PluginEntity.PLUGIN,
        entity_id=f"{plugin.id}:atom-sweep",
        actor_id=actor_id,
        payload={"id": plugin.id, **summary},
    )
    return summary


async def uninstall(session: AsyncSession, plugin_id: str, actor_id: uuid.UUID | None = None) -> None:
    """Remove an installable plugin's record (keeps data by default — a separate purge
    drops its tables, §10). Bootstrap builtins can't be uninstalled — only disabled.
    RADD-818: the atom sweep runs first, so roles/token scopes/grants never keep
    vocabulary the catalog no longer knows."""
    plugin, _path, kind = _resolve_toggleable(plugin_id)
    if kind == PluginOrigin.BOOTSTRAP.value:
        raise ConflictError(
            PluginEntity.PLUGIN, reason=f"{plugin_id} is a builtin — disable it instead of uninstalling"
        )
    _ensure_no_dependents(plugin)
    await sweep_plugin_atoms(session, plugin, actor_id)
    row = await _row(session, plugin_id)
    if row is not None:
        await session.delete(row)
        await session.flush()
    await _emit(session, PluginEvent.UNINSTALLED, plugin_id, actor_id)
