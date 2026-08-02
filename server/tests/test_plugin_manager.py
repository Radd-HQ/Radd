"""The plugin manager lifecycle (spec 93 / A4, docs/plugin-platform.md §10).

DB-backed but rolled back. Proves the DONE gate: the manager enumerates every plugin
with its state, core plugins are locked, and a non-core plugin can be installed /
enabled / disabled / uninstalled — the state that `create_app` resolves at boot and
the live API hot-mounts on.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.pluginmgr import service
from radd.modules.pluginmgr.types import PluginState

MILESTONES = "radd.milestones"


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def test_lists_core_and_installable_with_state(db):
    infos = {i.id: i for i in await service.list_plugins(db)}
    # a well-known core plugin is present, locked
    assert infos["events"].core is True
    assert infos["events"].can_toggle is False
    assert infos["events"].state is PluginState.ENABLED
    # the north-star plugin is installable + toggleable, DISCOVERED until installed
    assert infos[MILESTONES].core is False
    assert infos[MILESTONES].can_toggle is True
    assert infos[MILESTONES].state is PluginState.DISCOVERED


async def test_enable_then_disable_roundtrip(db):
    await service.enable(db, MILESTONES)
    infos = {i.id: i for i in await service.list_plugins(db)}
    assert infos[MILESTONES].state is PluginState.ENABLED
    await service.disable(db, MILESTONES)
    infos = {i.id: i for i in await service.list_plugins(db)}
    assert infos[MILESTONES].state is PluginState.DISABLED


async def test_install_is_idempotent_when_a_row_exists(db):
    # Regression: install once (creates a row), then install again — the second call must NOT crash
    # (there is no UNINSTALLED row state; the old code referenced a missing enum member).
    await service.install(db, MILESTONES)
    await service.install(db, MILESTONES)
    infos = {i.id: i for i in await service.list_plugins(db)}
    assert infos[MILESTONES].state is PluginState.INSTALLED
    # Installing over an ENABLED plugin is a no-op (stays enabled), not a downgrade.
    await service.enable(db, MILESTONES)
    await service.install(db, MILESTONES)
    infos = {i.id: i for i in await service.list_plugins(db)}
    assert infos[MILESTONES].state is PluginState.ENABLED


async def test_install_is_installed_not_enabled(db):
    await service.install(db, MILESTONES)
    infos = {i.id: i for i in await service.list_plugins(db)}
    assert infos[MILESTONES].state is PluginState.INSTALLED


async def test_uninstall_returns_to_discovered(db):
    await service.enable(db, MILESTONES)
    await service.uninstall(db, MILESTONES)
    infos = {i.id: i for i in await service.list_plugins(db)}
    assert infos[MILESTONES].state is PluginState.DISCOVERED


async def test_cannot_disable_a_core_plugin(db):
    with pytest.raises(ConflictError):
        await service.disable(db, "events")  # core → locked


async def test_optional_bootstrap_plugin_is_toggleable(db):
    infos = {i.id: i for i in await service.list_plugins(db)}
    # ldap ships in config.modules but is core=False → on by default, disableable
    assert infos["ldap"].core is False
    assert infos["ldap"].can_toggle is True
    assert infos["ldap"].state is PluginState.ENABLED


async def test_disable_an_optional_bootstrap_plugin(db):
    await service.disable(db, "ldap")
    infos = {i.id: i for i in await service.list_plugins(db)}
    assert infos["ldap"].state is PluginState.DISABLED
    # re-enable returns it to the default
    await service.enable(db, "ldap")
    infos = {i.id: i for i in await service.list_plugins(db)}
    assert infos["ldap"].state is PluginState.ENABLED


async def test_dependency_guard_blocks_disabling_a_needed_plugin(db):
    # csat depends_on mailintake — can't disable mailintake while csat is loaded
    with pytest.raises(ConflictError):
        await service.disable(db, "mailintake")


async def test_cannot_uninstall_a_builtin(db):
    with pytest.raises(ConflictError):
        await service.uninstall(db, "ldap")  # bootstrap builtin → disable, don't uninstall


async def test_unknown_plugin_404(db):
    with pytest.raises(NotFoundError):
        await service.enable(db, "acme.nonexistent")


async def test_disable_when_not_enabled_conflicts(db):
    with pytest.raises(ConflictError):
        await service.disable(db, MILESTONES)  # DISCOVERED, never enabled


async def test_contribution_settings_roundtrip_scoped_by_name(db):
    """Instance-wide contribution settings (spec 94): a plugin's `"<slot>::<id>"` keys round-trip,
    and the aggregate read prefixes them with the plugin's registry NAME (what the SDK matches on)."""
    from radd.modules.pluginmgr import discovery

    name = discovery.all_known()[MILESTONES][0].name
    await service.enable(db, MILESTONES)  # a loaded plugin: the realistic path (row exists, ENABLED)

    assert await service.contribution_settings_all(db) == []
    await service.set_contribution_settings(db, MILESTONES, ["issue.tab::notes", "view.header::sum"])
    got = set(await service.contribution_settings_all(db))
    assert got == {f"{name}::issue.tab::notes", f"{name}::view.header::sum"}

    # Setting contribution availability must NOT change the plugin's own lifecycle state.
    infos = {i.id: i for i in await service.list_plugins(db)}
    assert infos[MILESTONES].state is PluginState.ENABLED

    # Replacing with an empty set clears them.
    await service.set_contribution_settings(db, MILESTONES, [])
    assert await service.contribution_settings_all(db) == []


async def test_contribution_settings_get_or_create_preserves_default_state(db):
    """Persisting a setting for a plugin with NO row seeds the row at its DEFAULT state — never
    silently enabling an installable plugin that was only DISCOVERED."""
    await service.set_contribution_settings(db, MILESTONES, ["issue.tab::x"])
    infos = {i.id: i for i in await service.list_plugins(db)}
    assert infos[MILESTONES].state is PluginState.DISCOVERED


async def test_contribution_settings_unknown_plugin_404(db):
    with pytest.raises(NotFoundError):
        await service.set_contribution_settings(db, "acme.nonexistent", [])
