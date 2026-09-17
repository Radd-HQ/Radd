"""Managed wheel uploads and conservative live lifecycle, isolated from dev files."""
import io
import json
import stat
import sys
import uuid
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from radd.kernel import RaddPlugin, registries
from radd.modules.pluginmgr import discovery, live, service, store


@pytest.fixture
def plugin_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store.settings, 'plugins_dir', str(tmp_path / 'plugins'))
    before = set(sys.modules)
    yield tmp_path / 'plugins'
    for path in list(sys.path):
        if path.startswith(str(tmp_path)):
            sys.path.remove(path)
    for key in set(sys.modules) - before:
        module = sys.modules.get(key)
        if str(getattr(module, '__file__', '')).startswith(str(tmp_path)):
            del sys.modules[key]
    store._managed_paths.clear()


def wheel(*, module=None, extra=None, source=None, requirements=''):
    module = module or f'fixture_{uuid.uuid4().hex}'
    name = module.replace('_', '-')
    root = f'{module}-1.0.0.dist-info'
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr(f'{root}/METADATA', f'Metadata-Version: 2.1\nName: {name}\nVersion: 1.0.0\n{requirements}')
        z.writestr(f'{root}/WHEEL', 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        z.writestr(f'{root}/entry_points.txt', f'[radd.plugins]\n{name} = {module}\n')
        z.writestr(f'{module}/__init__.py', source or
                   f'from radd.sdk import RaddPlugin\nplugin=RaddPlugin(name="{name}",version="1.0.0",core=False)\n')
        for key, value in (extra or {}).items():
            z.writestr(key, value)
    return out.getvalue()


def test_install_publishes_discoverable_package_and_cleans_staging(plugin_store):
    info = store.install_wheel(wheel())
    assert info['id'] in discovery.installable_plugins()
    assert (plugin_store / 'packages' / info['sha256']).is_dir()
    assert list(plugin_store.glob('.staging-*')) == []
    assert list(plugin_store.glob('.catalog-*')) == []


@pytest.mark.parametrize('badpath', ['../escape.py', '/absolute.py', 'radd/override.py', 'evil.pth'])
def test_archive_escape_and_foreign_files_rejected_without_residue(plugin_store, badpath):
    with pytest.raises(store.PackageError, match='archive path'):
        store.install_wheel(wheel(extra={badpath: 'unsafe'}))
    assert store.catalog() == {}
    assert list(plugin_store.glob('.staging-*')) == []
    assert not (plugin_store / 'packages').exists()


def test_symlink_rejected(plugin_store):
    module = f'symlink_{uuid.uuid4().hex}'
    data = io.BytesIO(wheel(module=module))
    with zipfile.ZipFile(data, 'a') as z:
        link = zipfile.ZipInfo(f'{module}/link')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(link, '/etc/passwd')
    with pytest.raises(store.PackageError, match='archive path'):
        store.install_wheel(data.getvalue())


def test_missing_dependency_rejected_before_import(plugin_store):
    with pytest.raises(store.PackageError, match='not installed'):
        store.install_wheel(wheel(requirements='Requires-Dist: radd-missing-fixture-dependency==99\n'))
    assert store.catalog() == {}


def test_failed_manifest_validation_cleans_up(plugin_store):
    with pytest.raises(store.PackageError, match='validation failed'):
        store.install_wheel(wheel(source='raise RuntimeError("bad plugin")'))
    assert store.catalog() == {}
    assert list(plugin_store.glob('.staging-*')) == []


def test_stdlib_collision_is_rejected(plugin_store):
    with pytest.raises(store.PackageError, match='already exists'):
        store.install_wheel(wheel(module='json'))


def test_size_limit(plugin_store, monkeypatch):
    monkeypatch.setattr(store, 'MAX_BYTES', 10)
    with pytest.raises(store.PackageError, match='upload limit'):
        store.install_wheel(b'a' * 11)


async def test_live_enable_disable_then_remove_cleans_owned_files(plugin_store, monkeypatch):
    info = store.install_wheel(wheel())
    monkeypatch.setattr(service, '_states', AsyncMock(return_value={info['id']: SimpleNamespace(state='enabled')}))
    await live.reconcile()
    assert info['id'] in registries.plugins
    assert live.reports()[0]['active'].count(info['id']) == 1
    with pytest.raises(store.PackageError, match='active or unconfirmed'):
        store.remove(info['id'])
    monkeypatch.setattr(service, '_states', AsyncMock(return_value={}))
    await live.reconcile()
    assert info['id'] not in registries.plugins
    store.remove(info['id'])
    assert store.catalog() == {}
    assert not (plugin_store / 'packages' / info['sha256']).exists()
    assert info['id'] not in discovery.installable_plugins()


def test_stale_process_prevents_cleanup(plugin_store):
    info = store.install_wheel(wheel())
    directory = plugin_store / 'runtime'
    directory.mkdir()
    (directory / 'stale.json').write_text(json.dumps({'process':'stale','updated_at':0,'active':[]}))
    with pytest.raises(store.PackageError, match='unconfirmed'):
        store.remove(info['id'])
    assert info['distribution'] in store.catalog()


def test_backend_hooks_and_tasks_are_not_live_capable():
    from radd.kernel.specs import TaskSpec
    assert live.supported(RaddPlugin(name='ui', core=False))
    assert not live.supported(RaddPlugin(name='hook', core=False, on_startup=(AsyncMock(),)))
    assert not live.supported(RaddPlugin(name='task', core=False, tasks=(TaskSpec(name='job', run=AsyncMock()),)))
    assert not live.supported(RaddPlugin(name='core'))


def test_installer_lock_is_nonblocking_for_live_poll(plugin_store):
    with store.locked():
        with pytest.raises(BlockingIOError):
            with store.locked(blocking=False):
                pytest.fail('lock unexpectedly acquired')


async def test_upload_rejects_non_admin_before_reading_request():
    from radd.exceptions import ForbiddenError
    from radd.modules.pluginmgr.router import upload_package
    request = SimpleNamespace(stream=lambda: pytest.fail('read unauthorized body'))
    user = SimpleNamespace(active=True, instance_role='member', token_scope=None)
    with pytest.raises(ForbiddenError):
        await upload_package(request, AsyncMock(), user)


async def test_upload_enforces_stream_limit_before_install(monkeypatch):
    from fastapi import HTTPException
    from radd.modules.pluginmgr.router import upload_package
    monkeypatch.setattr(store, 'MAX_BYTES', 4)
    async def chunks():
        yield b'123'
        yield b'456'
    user = SimpleNamespace(active=True, instance_role='admin', token_scope=None)
    with pytest.raises(HTTPException) as error:
        await upload_package(SimpleNamespace(stream=chunks), AsyncMock(), user)
    assert error.value.status_code == 413


def test_two_processes_must_both_disable_before_removal(plugin_store):
    import os
    import select
    import subprocess
    info = store.install_wheel(wheel())
    script = '''
import asyncio,json,sys
from types import SimpleNamespace
from radd.modules.pluginmgr import live,service
from radd.kernel import registries
for line in sys.stdin:
    command=json.loads(line)
    if command.get("stop"):
        asyncio.run(live.stop()); break
    async def states(session):
        return {command["id"]:SimpleNamespace(state=command["state"])}
    service._states=states
    asyncio.run(live.reconcile())
    print(json.dumps({"active":list(registries.plugins)}),flush=True)
'''
    env = {**os.environ, 'RADD_PLUGINS_DIR': str(plugin_store)}
    peers = [subprocess.Popen([sys.executable, '-u', '-c', script], env=env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for _ in range(2)]
    def command(peer, state):
        peer.stdin.write(json.dumps({'id':info['id'],'state':state})+'\n')
        peer.stdin.flush()
        assert select.select([peer.stdout], [], [], 15)[0], 'peer failed to acknowledge'
        return json.loads(peer.stdout.readline())
    try:
        for peer in peers:
            assert info['id'] in command(peer, 'enabled')['active']
        assert len(live.reports()) == 2
        assert info['id'] not in command(peers[0], 'disabled')['active']
        with pytest.raises(store.PackageError, match='active or unconfirmed'):
            store.remove(info['id'])
        assert info['id'] not in command(peers[1], 'disabled')['active']
        store.remove(info['id'])
        assert store.catalog() == {}
    finally:
        for peer in peers:
            try:
                peer.communicate('{"stop":true}\n', timeout=5)
            except (subprocess.TimeoutExpired, BrokenPipeError):
                peer.kill()
                peer.communicate()


async def test_upload_endpoint_audits_valid_package(plugin_store):
    from radd.db import SessionLocal
    from radd.modules.pluginmgr.router import upload_package
    payload = wheel()
    async def chunks():
        yield payload[:20]
        yield payload[20:]
    user = SimpleNamespace(active=True, instance_role='admin', token_scope=None, id=None)
    async with SessionLocal() as session:
        result = await upload_package(SimpleNamespace(stream=chunks), session, user)
        assert result['distribution'] in store.catalog()
        await session.rollback()


def test_next_install_cleans_interrupted_staging_and_unpublished_artifacts(plugin_store):
    (plugin_store / '.staging-interrupted').mkdir(parents=True)
    (plugin_store / '.catalog-interrupted').write_text('{}')
    orphan = plugin_store / 'packages' / ('a' * 64)
    orphan.mkdir(parents=True)
    info = store.install_wheel(wheel())
    assert not orphan.exists()
    assert not (plugin_store / '.staging-interrupted').exists()
    assert not (plugin_store / '.catalog-interrupted').exists()
    assert (plugin_store / 'packages' / info['sha256']).exists()
