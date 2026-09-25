"""Reconcile committed plugin state in every web/worker, with leased acknowledgements."""
import asyncio
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
from datetime import datetime, UTC, timedelta
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert
from .models import PluginProcess
from radd.kernel.runtime import gate


logger = logging.getLogger(__name__)
_task: asyncio.Task | None = None
_process = f'{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}'
_error: str | None = None
_last_state: tuple | None = None
_runtime = None
_errors: dict[str, str] = {}
_pending: set[str] = set()
_observed: set[str] = set()
_versions: dict[str, str] = {}
_heartbeat_lock = asyncio.Lock()
_lock = asyncio.Lock()


def bind(runtime):
    global _runtime
    _runtime = runtime


def supported(plugin: RaddPlugin) -> bool:
    return not plugin.core


async def cluster_reports(session):
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = (await session.execute(select(PluginProcess))).scalars()
    return [{**row.report, 'stale': now - row.updated_at > timedelta(seconds=30)} for row in rows]


def state_version(row):
    return f"{row.state}:{getattr(row, 'updated_at', '')}" if row is not None else 'bootstrap'


async def heartbeat():
    async with _heartbeat_lock:
        await _write_heartbeat()


async def _write_heartbeat():
    started = time.monotonic()
    record = {'process': _process, 'active': list(registries.plugins),
              'observed': sorted(_observed), 'versions': dict(_versions), 'pending': sorted(_pending),
              'errors': dict(_errors), 'error': _error, 'updated_at': time.time()}
    now = datetime.now(UTC).replace(tzinfo=None)
    async with SessionLocal() as session:
        statement = insert(PluginProcess).values(process_id=_process, report=record, updated_at=now)
        await session.execute(statement.on_conflict_do_update(
            index_elements=['process_id'], set_={'report': record, 'updated_at': now}))
        await session.execute(delete(PluginProcess).where(PluginProcess.updated_at < now - timedelta(days=1)))
        await session.commit()
    gate.lease_until = started + 25


async def _heartbeats():
    while True:
        try:
            await heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Plugin heartbeat failed; admissions stop when lease expires')
        await asyncio.sleep(5)


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
    global _last_state, _observed, _versions
    from .service import _states

    async with _lock:
        async with SessionLocal() as session:
            rows = await _states(session)
        with store.locked(blocking=False):
            builtins = discovery.core_plugins()
            known = {**builtins, **discovery.installable_plugins()}
        desired = {pid for pid, (p, _) in known.items() if p.core or (
            rows[pid].state == PluginState.ENABLED if pid in rows
            else pid in builtins and p.enabled_by_default)}
        _observed = desired
        _versions = {pid: state_version(row) for pid, row in rows.items()}
        # Dependents stop first; dependencies start first. No desired state is
        # applied until its transaction committed, and no registry is torn down
        # underneath an admitted request or a worker tick.
        for pid in reversed(list(registries.plugins)):
            if pid in desired or registries.plugins[pid].core:
                continue
            plugin = registries.plugins[pid]
            dependents = [p.name for p in registries.plugins.values() if plugin.name in p.depends_on]
            if dependents:
                _errors[pid] = 'Still required by: ' + ', '.join(dependents)
                continue
            _pending.add(pid)
            try:
                if _runtime is not None:
                    await _runtime.disable(plugin)
                else:
                    # Isolated tooling/tests can reconcile declarations without
                    # an ASGI application. Never pretend backend hooks ran.
                    if plugin.routers or plugin.on_startup or plugin.tasks or plugin.entities:
                        raise RuntimeError('Runtime application is not bound')
                    registries.unregister_plugin(plugin)
                _errors.pop(pid, None)
            except Exception as exc:
                _errors[pid] = f'{type(exc).__name__}: disable failed; will retry'
                logger.exception('Disabling plugin %s failed', pid)
            finally:
                _pending.discard(pid)
        waiting = desired - set(registries.plugins)
        while waiting:
            ready = [pid for pid in waiting if not plugin_problems(
                known[pid][0], {p.name for p in registries.plugins.values()})]
            if not ready:
                for pid in waiting:
                    _errors[pid] = '; '.join(plugin_problems(
                        known[pid][0], {p.name for p in registries.plugins.values()}))
                break
            for pid in ready:
                plugin, path = known[pid]
                _pending.add(pid)
                try:
                    if _runtime is not None:
                        await _runtime.enable(plugin, path)
                    else:
                        if plugin.routers or plugin.on_startup or plugin.tasks or plugin.entities:
                            raise RuntimeError('Runtime application is not bound')
                        import importlib
                        registries.register_plugin(plugin)
                        registries.register_plugin_ui_dir(plugin, importlib.import_module(path))
                    _errors.pop(pid, None)
                except Exception as exc:
                    _errors[pid] = f'{type(exc).__name__}: enable failed; will retry'
                    logger.exception('Enabling plugin %s failed', pid)
                finally:
                    _pending.discard(pid)
                    waiting.remove(pid)
        # A cancelled request (enable followed by disable) clears its old error.
        for pid in list(_errors):
            if (pid in registries.plugins) == (pid in desired) and pid not in _pending:
                _errors.pop(pid, None)
        acknowledge()

async def _run() -> None:
    global _error
    while True:
        try:
            _error = None
            await reconcile()
            await heartbeat()
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


_heartbeat_task: asyncio.Task | None = None


async def start() -> None:
    global _task, _heartbeat_task, _observed, _process, _versions
    if _task is None:
        # Assigned after worker forks, never inherited from a preloaded parent.
        _process = f'{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}'
        _versions = {}
        _observed = set(registries.plugins)
        await heartbeat()
        acknowledge()
        _heartbeat_task = asyncio.create_task(_heartbeats(), name='plugin-heartbeats')
        _task = asyncio.create_task(_run(), name='plugin-reconciliation')


async def stop() -> None:
    global _task, _heartbeat_task, _runtime
    tasks = [t for t in (_task, _heartbeat_task) if t is not None]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _task = _heartbeat_task = None
    gate.lease_until = None
    async with SessionLocal() as session:
        await session.execute(delete(PluginProcess).where(PluginProcess.process_id == _process))
        await session.commit()
    (store.root() / 'runtime' / f'{_process}.json').unlink(missing_ok=True)
    _runtime = None
