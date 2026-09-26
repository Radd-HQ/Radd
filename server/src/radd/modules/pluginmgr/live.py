"""Apply committed plugin state in every web/worker process (RADD-1341, RADD-1372).

Each process polls `installed_plugins` and applies what changed through its
`PluginRuntime`. A poll is one small SELECT: discovery (entry points, the
managed package paths, imports, under the store's file lock) runs only when the
fingerprint of desired state + package catalog + loaded plugins moved, or when a
failed attempt is due for its retry. A failed apply retries after the reconcile
interval, doubling up to `plugin_retry_max_seconds`; a changed desired state
retries at once.

Acknowledgements go through ONE channel, `acks` (the `plugin_processes` row).
Errors are attributed: `_errors[plugin_id]` is a failure to apply THAT plugin
(shown on its row); `_error` is this process failing to reconcile at all (shown
once, from GET /plugins/runtime). Neither flickers: `_error` changes only when
an iteration has finished with a different verdict.
"""

import asyncio
import importlib
import logging
import time
from functools import partial

from radd.config import settings
from radd.db import SessionLocal
from radd.kernel import RaddPlugin, admission, registries
from radd.kernel.loader import plugin_problems

from . import acks, discovery, store
from .types import PluginState

logger = logging.getLogger(__name__)
_task: asyncio.Task | None = None
_heartbeat_task: asyncio.Task | None = None
_process = acks.new_process_id()
_runtime = None
_error: str | None = None
_errors: dict[str, str] = {}
_pending: set[str] = set()
_observed: set[str] = set()
_versions: dict[str, str] = {}
_fingerprint: tuple | None = None
#: plugin id -> (desired, retry at [monotonic], current delay)
_backoff: dict[str, tuple[bool, float, float]] = {}
_heartbeat_lock = asyncio.Lock()
_lock = asyncio.Lock()


def bind(runtime):
    global _runtime
    _runtime = runtime


def supported(plugin: RaddPlugin) -> bool:
    return not plugin.core


def _report() -> dict:
    return {"active": list(registries.plugins), "observed": sorted(_observed),
            "versions": dict(_versions), "pending": sorted(_pending),
            "errors": dict(_errors), "error": _error}


async def heartbeat():
    async with _heartbeat_lock:
        await acks.publish(_process, _report())


async def _heartbeats():
    while True:
        try:
            await heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Plugin heartbeat failed; non-core plugin work stops when the lease lapses")
        await asyncio.sleep(settings.plugin_heartbeat_seconds)


def _fingerprint_of(rows) -> tuple:
    catalog = store.root() / "catalog.json"
    return (
        str(store.root()),
        catalog.stat().st_mtime_ns if catalog.exists() else None,
        tuple(sorted((pid, row.state, str(getattr(row, "updated_at", ""))) for pid, row in rows.items())),
        tuple(registries.plugins),
    )


def _retry_due() -> bool:
    now = time.monotonic()
    return any(at <= now for _desired, at, _delay in _backoff.values())


def _has_backend(plugin: RaddPlugin) -> bool:
    return bool(plugin.routers or plugin.on_startup or plugin.tasks or plugin.entities)


async def _enable(plugin: RaddPlugin, path: str) -> None:
    if _runtime is not None:
        await _runtime.enable(plugin, path)
        return
    # Isolated tooling/tests reconcile declarations without an ASGI application.
    # Never pretend backend hooks ran.
    if _has_backend(plugin):
        raise RuntimeError("Runtime application is not bound")
    registries.register_plugin(plugin)
    registries.register_plugin_ui_dir(plugin, importlib.import_module(path))


async def _disable(plugin: RaddPlugin) -> None:
    if _runtime is not None:
        await _runtime.disable(plugin)
        return
    if _has_backend(plugin):
        raise RuntimeError("Runtime application is not bound")
    registries.unregister_plugin(plugin)


async def _resume(plugin: RaddPlugin) -> None:
    if _runtime is not None:
        await _runtime.resume(plugin)
    admission.gate.open(plugin.id)


async def _attempt(plugin_id: str, desired: bool, action) -> None:
    entry = _backoff.get(plugin_id)
    if entry is not None and entry[0] == desired and time.monotonic() < entry[1]:
        return  # waiting out the backoff of an earlier failure
    _pending.add(plugin_id)
    try:
        await action()
    except admission.DrainTimeout as exc:
        _fail(plugin_id, desired, f"Waiting for {exc.in_flight} running request(s) or job(s) "
                                  "of this plugin to finish; retrying")
        logger.info("Plugin %s is still draining (%s)", plugin_id, exc)
    except Exception as exc:
        verb = "enable" if desired else "disable"
        _fail(plugin_id, desired, f"{type(exc).__name__}: {verb} failed; will retry")
        logger.exception("Applying plugin %s (%s) failed", plugin_id, verb)
    else:
        _errors.pop(plugin_id, None)
        _backoff.pop(plugin_id, None)
    finally:
        _pending.discard(plugin_id)


def _fail(plugin_id: str, desired: bool, message: str) -> None:
    _errors[plugin_id] = message
    entry = _backoff.get(plugin_id)
    delay = settings.plugin_reconcile_interval_seconds
    if entry is not None and entry[0] == desired:
        delay = min(entry[2] * 2, settings.plugin_retry_max_seconds)
    _backoff[plugin_id] = (desired, time.monotonic() + delay, delay)


async def _withdraw_undesired(desired: set[str]) -> None:
    """Dependents stop first; a cancelled pending disable reopens its plugin."""
    for pid in reversed(list(registries.plugins)):
        plugin = registries.plugins[pid]
        if plugin.core:
            continue
        if pid in desired:
            if pid in admission.gate.closed:
                await _attempt(pid, True, partial(_resume, plugin))
            continue
        dependents = [p.name for p in registries.plugins.values() if plugin.name in p.depends_on]
        if dependents:
            _errors[pid] = "Still required by: " + ", ".join(dependents)
            continue
        await _attempt(pid, False, partial(_disable, plugin))


async def _admit_desired(desired: set[str], known: dict) -> None:
    """Dependencies start first."""
    waiting = desired - set(registries.plugins)
    while waiting:
        loaded = {p.name for p in registries.plugins.values()}
        ready = [pid for pid in waiting if not plugin_problems(known[pid][0], loaded)]
        if not ready:
            for pid in waiting:
                _errors[pid] = "; ".join(plugin_problems(known[pid][0], loaded))
            return
        for pid in ready:
            plugin, path = known[pid]
            await _attempt(pid, True, partial(_enable, plugin, path))
            waiting.discard(pid)


def _forget_settled(desired: set[str]) -> None:
    """A request that was cancelled (enable, then disable) clears its old error.
    A loaded plugin that is still closed has a disable or resume outstanding."""
    for pid in list(_errors):
        loaded = pid in registries.plugins
        settled = loaded == (pid in desired) and not (loaded and pid in admission.gate.closed)
        if settled and pid not in _pending:
            _errors.pop(pid, None)
    for pid in list(_backoff):
        if pid not in _errors:
            _backoff.pop(pid)


async def reconcile() -> bool:
    """Apply committed desired state. Returns whether anything was examined (the
    caller then publishes a fresh acknowledgement); False when nothing moved."""
    global _fingerprint, _observed, _versions
    from .service import _states

    async with _lock:
        async with SessionLocal() as session:
            rows = await _states(session)
        if _fingerprint_of(rows) == _fingerprint and not _retry_due():
            return False
        # Serializes against package publication/removal; never blocks the loop.
        with store.locked(blocking=False):
            builtins = discovery.core_plugins()
            known = {**builtins, **discovery.installable_plugins()}
        desired = {pid for pid, (p, _) in known.items() if p.core or (
            rows[pid].state == PluginState.ENABLED if pid in rows
            else pid in builtins and p.enabled_by_default)}
        _observed = desired
        _versions = {pid: acks.state_version(row) for pid, row in rows.items()}
        # No desired state is applied until its transaction committed, and no
        # registry is torn down underneath the changing plugin's own admitted work.
        await _withdraw_undesired(desired)
        await _admit_desired(desired, known)
        _forget_settled(desired)
        _fingerprint = _fingerprint_of(rows)
        return True


async def _run() -> None:
    global _error
    while True:
        changed, error = False, _error
        try:
            changed = await reconcile()
            error = None
        except BlockingIOError:
            pass  # installer owns the store; never block the API event loop — keep the last verdict
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: reconciliation failed"
            if error != _error:
                logger.exception("Plugin reconciliation failed")
            else:
                logger.debug("Plugin reconciliation still failing", exc_info=True)
        if changed or error != _error:
            _error = error
            try:
                await heartbeat()
            except Exception:
                logger.exception("Publishing the plugin acknowledgement failed; the heartbeat retries")
        await asyncio.sleep(settings.plugin_reconcile_interval_seconds)


async def start() -> None:
    global _task, _heartbeat_task, _observed, _process, _versions, _fingerprint, _error
    if _task is not None:
        return
    # Assigned after worker forks, never inherited from a preloaded parent.
    _process = acks.new_process_id()
    _versions, _observed, _fingerprint, _error = {}, set(registries.plugins), None, None
    _errors.clear()
    _backoff.clear()
    await heartbeat()
    _heartbeat_task = asyncio.create_task(_heartbeats(), name="plugin-heartbeats")
    _task = asyncio.create_task(_run(), name="plugin-reconciliation")


async def halt() -> None:
    """Stop reconciling and heartbeating. Cancellation only, so it cannot fail:
    nothing may enable a plugin while the process shuts its plugins down."""
    global _task, _heartbeat_task
    tasks = [t for t in (_task, _heartbeat_task) if t is not None]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _task = _heartbeat_task = None


async def withdraw() -> None:
    global _runtime
    _runtime = None
    await acks.withdraw(_process)


async def stop() -> None:
    await halt()
    await withdraw()
