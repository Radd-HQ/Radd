"""Failure paths for external delivery and restart-based lifecycle."""
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import ProgrammingError

from radd.exceptions import ConflictError
from radd.kernel import RaddPlugin, registries
from radd.kernel.registry import KernelRegistries
from radd.kernel.specs import TaskSpec
from radd.modules.pluginmgr import boot, discovery, service
from radd.plugin_cli import CheckError, scaffold, check


def test_scaffold_refuses_overwrite(tmp_path):
    root = tmp_path / 'plugin'
    scaffold(root, 'sample-plugin')
    with pytest.raises(CheckError, match='already exists'):
        scaffold(root, 'sample-plugin')
    assert check(root)['id'] == 'sample-plugin'


def test_scaffold_rejects_path_injection(tmp_path):
    with pytest.raises(CheckError):
        scaffold(tmp_path / 'plugin', '../outside')
    assert not (tmp_path / 'plugin').exists()


def test_check_rejects_version_drift(tmp_path):
    root = tmp_path / 'other'
    scaffold(root, 'version-fixture')
    file = root / 'pyproject.toml'
    file.write_text(file.read_text().replace('0.1.0', '0.2.0'))
    with pytest.raises(CheckError, match='version must match'):
        check(root)


async def test_rejected_core_uninstall_does_not_touch_runtime(monkeypatch):
    route = importlib.import_module('radd.modules.pluginmgr.router')
    monkeypatch.setattr(route, '_require_admin', lambda user: None)
    before = dict(registries.plugins)
    with pytest.raises(ConflictError):
        await route.uninstall('events', AsyncMock(), SimpleNamespace(id=None))
    assert registries.plugins == before


def test_unregister_removes_owned_tasks_and_consumers():
    registry = KernelRegistries()
    task = TaskSpec(name='fixture.task', run=AsyncMock())
    plugin = RaddPlugin(name='fixture', core=False, tasks=(task,), consumer_names=('fixture',))
    registry.register_plugin(plugin)
    registry.unregister_plugin(plugin)
    assert 'fixture.task' not in registry.tasks
    assert 'fixture' not in registry.consumer_names


def test_external_boot_dependency_order(monkeypatch):
    a = RaddPlugin(name='a', core=False)
    b = RaddPlugin(name='b', core=False, depends_on=('a',))
    monkeypatch.setattr(boot, 'plugin_states', lambda: {'a': 'enabled', 'b': 'enabled'})
    monkeypatch.setattr(discovery, 'core_plugins', lambda: {})
    monkeypatch.setattr(discovery, 'installable_plugins', lambda: {'b': (b, 'pkg_b'), 'a': (a, 'pkg_a')})
    assert boot.resolve_boot_paths() == ('pkg_a', 'pkg_b')


def test_boot_rejects_missing_dependency(monkeypatch):
    from radd.kernel.loader import PluginLoadError
    b = RaddPlugin(name='b', core=False, depends_on=('missing',))
    monkeypatch.setattr(boot, 'plugin_states', lambda: {'b': 'enabled'})
    monkeypatch.setattr(discovery, 'core_plugins', lambda: {})
    monkeypatch.setattr(discovery, 'installable_plugins', lambda: {'b': (b, 'pkg_b')})
    with pytest.raises(PluginLoadError, match='missing or cyclic'):
        boot.resolve_boot_paths()


def test_boot_does_not_mask_schema_errors(monkeypatch):
    from unittest.mock import MagicMock
    engine = MagicMock()
    engine.connect.return_value.__enter__.side_effect = ProgrammingError(
        'SELECT', {}, SimpleNamespace(sqlstate='42703'))
    monkeypatch.setattr(boot, 'create_engine', lambda url: engine)
    with pytest.raises(ProgrammingError):
        boot.plugin_states()
    engine.dispose.assert_called_once()


async def test_enable_rejects_incompatible_package_before_write(monkeypatch):
    plugin = RaddPlugin(name='incompatible', core=False, api_version='99.0')
    monkeypatch.setattr(discovery, 'installable_plugins', lambda: {plugin.id: (plugin, 'fixture')})
    session = AsyncMock()
    monkeypatch.setattr(service, '_states', AsyncMock(return_value={}))
    with pytest.raises(ConflictError, match='API'):
        await service.enable(session, plugin.id)
    session.flush.assert_not_called()


async def test_enable_only_saves_desired_state(monkeypatch):
    plugin = RaddPlugin(name='restart-fixture', core=False)
    monkeypatch.setattr(discovery, 'installable_plugins', lambda: {plugin.id: (plugin, 'fixture')})
    monkeypatch.setattr(service, '_states', AsyncMock(return_value={}))
    save = AsyncMock(return_value=SimpleNamespace(state='enabled'))
    monkeypatch.setattr(service, '_upsert', save)
    monkeypatch.setattr(service, '_emit', AsyncMock())
    await service.enable(AsyncMock(), plugin.id)
    save.assert_awaited_once()
    assert plugin.id not in registries.plugins


def test_broken_entrypoint_has_diagnostic(monkeypatch):
    def broken():
        raise ImportError('missing example dependency')
    monkeypatch.setattr(discovery, 'entry_points', lambda **kw: [SimpleNamespace(name='broken', load=broken)])
    assert discovery.entrypoint_plugins() == {}
    assert 'missing example dependency' in discovery.discovery_errors['broken']


def test_external_package_cannot_replace_core_identity(monkeypatch):
    core = RaddPlugin(name='core-fixture')
    impostor = RaddPlugin(name='core-fixture', core=False)
    monkeypatch.setattr(discovery, 'core_plugins', lambda: {core.id: (core, 'builtin')})
    monkeypatch.setattr(discovery.settings, 'installable_plugins', ())
    monkeypatch.setattr(discovery, 'entry_points', lambda **kw: [
        SimpleNamespace(name='impostor', value='impostor', load=lambda: impostor)])
    assert core.id not in discovery.installable_plugins()
    assert 'collides' in discovery.discovery_errors[core.id]


async def test_missing_package_is_visible_in_management(monkeypatch):
    monkeypatch.setattr(service, '_states', AsyncMock(return_value={
        'lost-package': SimpleNamespace(version='1.0.0', state='enabled')}))
    infos = {i.id: i for i in await service.list_plugins(AsyncMock())}
    assert infos['lost-package'].origin == 'missing'
    assert not infos['lost-package'].can_toggle
    assert 'Restore the package' in infos['lost-package'].problems[0]


async def test_pending_activation_reports_restart_requirement(monkeypatch):
    plugin = RaddPlugin(name='pending-package', core=False)
    monkeypatch.setattr(discovery, 'installable_plugins', lambda: {plugin.id: (plugin, 'fixture')})
    monkeypatch.setattr(service, '_states', AsyncMock(return_value={
        plugin.id: SimpleNamespace(version='0.0.0', state='enabled')}))
    infos = {i.id: i for i in await service.list_plugins(AsyncMock())}
    assert infos[plugin.id].restart_required
    assert not infos[plugin.id].active
