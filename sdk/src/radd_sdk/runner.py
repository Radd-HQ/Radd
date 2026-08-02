# Copyright 2026 the Radd authors
# SPDX-License-Identifier: Apache-2.0
"""Plugin loader + poll/dispatch/checkpoint loop (shotgunEvents-style).

Drop ``*.py`` files in a plugins dir; each defines ``register(reg)`` and calls
``reg.on(event_type_glob, callback)``. The runner polls ``GET /events``,
dispatches each event to matching callbacks as ``callback(client, event)``, and
checkpoints the stream offset to a JSON file after each batch (at-least-once).
A plugin exception is logged and skips that plugin for that event — never the
loop. An mtime change re-imports the plugin before the next batch (hot reload).
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .types import DEFAULT_POLL_INTERVAL, MAX_EVENTS_LIMIT, PLUGIN_ENTRYPOINT, Event, StateKey

log = logging.getLogger("radd_sdk.runner")

Callback = Callable[[Any, Event], None]


class EventSource(Protocol):
    """The one client capability the runner itself needs (tests stub this)."""

    def events(self, after: int = ..., limit: int = ...) -> list[Event]: ...


class Registry:
    """Passed to a plugin's ``register(reg)``; collects (glob, callback) routes.

    Globs are ``fnmatch`` patterns over the event type: ``item.*``, ``*``,
    or an exact type like ``sla.breached``.
    """

    def __init__(self) -> None:
        self._routes: list[tuple[str, Callback]] = []

    def on(self, event_type_glob: str, callback: Callback) -> None:
        self._routes.append((event_type_glob, callback))

    def matches(self, event_type: str) -> list[Callback]:
        return [cb for pattern, cb in self._routes if fnmatch.fnmatchcase(event_type, pattern)]


@dataclass(slots=True)
class Plugin:
    """A loaded plugin file: its routes plus the mtime we imported it at."""

    name: str
    path: Path
    mtime: float
    registry: Registry


def _load_plugin(path: Path) -> Plugin | None:
    """Import one plugin file and run its ``register(reg)``. None on any failure."""
    name = path.stem
    spec = importlib.util.spec_from_file_location(f"radd_plugin_{name}", path)
    if spec is None or spec.loader is None:
        log.error("plugin %s: cannot build import spec; skipping", path.name)
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        log.exception("plugin %s: import failed; skipping", path.name)
        return None
    register = getattr(module, PLUGIN_ENTRYPOINT, None)
    if not callable(register):
        log.error("plugin %s: no %s(reg) function; skipping", path.name, PLUGIN_ENTRYPOINT)
        return None
    registry = Registry()
    try:
        register(registry)
    except Exception:
        log.exception("plugin %s: %s(reg) raised; skipping", path.name, PLUGIN_ENTRYPOINT)
        return None
    return Plugin(name=name, path=path, mtime=path.stat().st_mtime, registry=registry)


def load_checkpoint(path: Path) -> int | None:
    """Saved stream offset, or None if the file is missing/unreadable."""
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        log.warning("checkpoint %s unreadable; ignoring", path)
        return None
    offset = data.get(StateKey.OFFSET)
    return int(offset) if offset is not None else None


def save_checkpoint(path: Path, offset: int) -> None:
    """Atomically write the stream offset (write temp file, then rename)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({StateKey.OFFSET: offset}))
    tmp.replace(path)


class Runner:
    """Polls the event stream, dispatches to plugins, checkpoints the offset.

    One stream cursor per runner process (deliberately no per-plugin offsets).
    With no checkpoint file: start at the current head, or at 0 when
    ``from_start=True``. Delivery is at-least-once — the offset is saved after
    each batch, so a crash mid-batch re-delivers that batch on restart.
    """

    def __init__(
        self,
        client: EventSource,
        plugins_dir: str | Path,
        state_path: str | Path,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        from_start: bool = False,
        batch_limit: int = MAX_EVENTS_LIMIT,
    ) -> None:
        self.client = client
        self.plugins_dir = Path(plugins_dir)
        self.state_path = Path(state_path)
        self.poll_interval = poll_interval
        self.batch_limit = batch_limit
        self._plugins: dict[Path, Plugin] = {}
        self._running = False
        self.offset = self._initial_offset(from_start)

    # -- offset ------------------------------------------------------------

    def _initial_offset(self, from_start: bool) -> int:
        saved = load_checkpoint(self.state_path)
        if saved is not None:
            return saved
        return 0 if from_start else self._current_head()

    def _current_head(self) -> int:
        """Latest event id — pages the stream forward without dispatching."""
        head = 0
        while True:
            batch = self.client.events(after=head, limit=self.batch_limit)
            if not batch:
                return head
            head = batch[-1].id

    # -- plugins -----------------------------------------------------------

    def refresh_plugins(self) -> None:
        """(Re)load new or mtime-changed ``*.py`` files; drop deleted ones."""
        seen: set[Path] = set()
        for path in sorted(self.plugins_dir.glob("*.py")):
            seen.add(path)
            current = self._plugins.get(path)
            mtime = path.stat().st_mtime
            if current is not None and current.mtime == mtime:
                continue
            log.info("%s plugin %s", "reloading" if current else "loading", path.name)
            plugin = _load_plugin(path)
            if plugin is not None:
                self._plugins[path] = plugin
            elif current is not None:
                del self._plugins[path]  # broken rewrite: don't keep dispatching stale code
        for path in [p for p in self._plugins if p not in seen]:
            log.info("plugin %s removed", path.name)
            del self._plugins[path]

    @property
    def plugins(self) -> list[Plugin]:
        return list(self._plugins.values())

    # -- dispatch ----------------------------------------------------------

    def dispatch(self, event: Event) -> None:
        """Route one event to every matching callback, isolating plugin crashes."""
        for plugin in self._plugins.values():
            for callback in plugin.registry.matches(event.event_type):
                try:
                    callback(self.client, event)
                except Exception:
                    log.exception(
                        "plugin %s failed on event %d (%s); skipping it for this event",
                        plugin.name,
                        event.id,
                        event.event_type,
                    )
                    break  # skip the rest of THIS plugin's handlers, never other plugins

    def poll_once(self) -> int:
        """One cycle: refresh plugins, fetch, dispatch, checkpoint. Returns batch size."""
        self.refresh_plugins()
        batch = self.client.events(after=self.offset, limit=self.batch_limit)
        for event in batch:
            self.dispatch(event)
        if batch:
            self.offset = batch[-1].id
            save_checkpoint(self.state_path, self.offset)
        return len(batch)

    # -- loop --------------------------------------------------------------

    def run(self) -> None:
        """Poll until ``stop()``; sleep ``poll_interval`` after an empty or failed poll."""
        self._running = True
        log.info("runner starting at offset %d (plugins dir: %s)", self.offset, self.plugins_dir)
        while self._running:
            try:
                processed = self.poll_once()
            except Exception:
                log.exception("poll failed; retrying in %.1fs", self.poll_interval)
                processed = 0
            if processed == 0 and self._running:
                time.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False
