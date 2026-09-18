"""Conservative live reconciliation: only manifests containing UI declarations.

Runs in EVERY web/worker process, reading committed desired state. Backend
hooks, tasks, entities and routes require restart until ownership/draining is
implemented. Filesystem acknowledgements prevent cleanup while peers use code.
"""
import asyncio
from dataclasses import fields
import importlib
import json
import logging
import os
import socket
import time
import uuid

from radd.db import SessionLocal
from radd.kernel import RaddPlugin, registries
from radd.kernel.loader import plugin_problems

from . import discovery, store
from .types import PluginState

logger = logging.getLogger(__name__)
_task: asyncio.Task | None = None
_process = f'{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}'
_error: str | None = None
_last_state: tuple | None = None
_ALLOWED = {'id', 'name', 'version', 'api_version', 'description', 'core', 'depends_on', 'weak_depends', 'ui'}


def supported(plugin: RaddPlugin) -> bool:
    baseline = RaddPlugin(name=plugin.name)
    return not plugin.core and all(
        f.name in _ALLOWED or getattr(plugin, f.name) == getattr(baseline, f.name)
        for f in fields(plugin)
    )


def reports() -> list[dict]:
    directory = store.root() / 'runtime'
    result = []
    if directory.exists():
        for path in directory.glob('*.json'):
            try:
                report = json.loads(path.read_text())
                report['stale'] = time.time() - report['updated_at'] > 30
                result.append(report)
            except (ValueError, OSError, KeyError):
                result.append({'process': path.stem, 'stale': True, 'active': [], 'error': 'Unreadable process report'})
    return result


def acknowledge() -> None:
    directory = store.root() / 'runtime'
    directory.mkdir(parents=True, exist_ok=True)
    record = {'process': _process, 'updated_at': time.time(),
              'active': list(registries.plugins), 'error': _error}
    temp = directory / f'.{_process}.tmp'
    temp.write_text(json.dumps(record))
    os.replace(temp, directory / f'{_process}.json')


def ensure_unused(plugin_id: str) -> None:
    peers = reports()
    if not peers:
        raise store.PackageError('No process acknowledgements yet; wait for plugin reconciliation')
    blockers = [r['process'] for r in peers if r['stale'] or r.get('error') or plugin_id in r['active']]
    if blockers:
        raise store.PackageError('Package is active or unconfirmed on processes: ' + ', '.join(blockers))


async def reconcile() -> None:
    global _last_state
    from .service import _states

    # Serializes against publication/removal of managed files across processes.
    # No await while holding the shared filesystem lock.
    async with SessionLocal() as session:
        rows = await _states(session)
    desired = {key for key, row in rows.items() if row.state == PluginState.ENABLED}
    catalog_file = store.root() / 'catalog.json'
    fingerprint = (str(store.root()), tuple(sorted(desired)), tuple(sorted(registries.plugins)),
                   catalog_file.stat().st_mtime_ns if catalog_file.exists() else None)
    if fingerprint == _last_state:
        acknowledge()
        return
    with store.locked(blocking=False):
        known = discovery.installable_plugins()
        for plugin_id, (plugin, path) in known.items():
            if not supported(plugin):
                continue
            active = registries.plugins.get(plugin_id)
            if plugin_id in desired and active is None:
                if plugin_problems(plugin, {p.name for p in registries.plugins.values()}):
                    continue
                registries.register_plugin(plugin)
                registries.register_plugin_ui_dir(plugin, importlib.import_module(path))
            elif plugin_id not in desired and active is not None:
                if any(plugin.name in p.depends_on for p in registries.plugins.values() if p.id != plugin_id):
                    continue
                registries.unregister_plugin(plugin)
        acknowledge()
        _last_state = fingerprint


async def _run() -> None:
    global _error
    while True:
        try:
            _error = None
            await reconcile()
        except BlockingIOError:
            pass  # installer owns the store; never block the API event loop
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _error = f'{type(exc).__name__}: reconciliation failed'
            logger.exception('Plugin reconciliation failed')
            try:
                acknowledge()
            except OSError:
                logger.exception('Cannot write plugin process acknowledgement')
        await asyncio.sleep(2)


async def start() -> None:
    global _task
    if _task is None:
        acknowledge()
        _task = asyncio.create_task(_run(), name='plugin-reconciliation')


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)
        _task = None
    (store.root() / 'runtime' / f'{_process}.json').unlink(missing_ok=True)
