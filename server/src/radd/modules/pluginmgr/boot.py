"""Which plugins load at boot (docs/plugin-platform.md §10): every core plugin in
`config.modules`; optional ones there unless DISABLED; installable ones when ENABLED.

A synchronous read, before routers mount. Only a MISSING `installed_plugins` table reads as
"no overrides" (fresh DB); anything else raises — guessing on a transient DB error would
silently change which plugins load (RADD-873).
"""

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from radd.config import settings

from . import discovery
from .types import PluginState

logger = logging.getLogger(__name__)


def plugin_states() -> dict[str, str]:
    """{plugin_id: state} for every installed_plugins row (empty only when the
    table does not exist yet — a fresh DB before the first migration)."""
    engine = create_engine(settings.database_url)  # psycopg3 works sync + async
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, state FROM installed_plugins")).all()
            return {r[0]: r[1] for r in rows}
    except ProgrammingError as exc:
        if getattr(exc.orig, "sqlstate", None) != "42P01":
            raise
        # UndefinedTable: alembic hasn't run yet. The one condition that
        # legitimately means "everything default".
        logger.info("installed_plugins missing — fresh database, no plugin overrides")
        return {}
    finally:
        engine.dispose()


def resolve_boot_paths() -> tuple[str, ...]:
    states = plugin_states()
    paths: list[str] = []
    # config.modules — core always; optional unless explicitly disabled
    for pid, (plugin, path) in discovery.core_plugins().items():
        state = states.get(pid)
        if plugin.core or state == PluginState.ENABLED.value or (
            state is None and plugin.enabled_by_default
        ):
            paths.append(path)
    # installable — only when enabled
    for pid, (_plugin, path) in discovery.installable_plugins().items():
        if states.get(pid) == PluginState.ENABLED.value:
            paths.append(path)
    # External distributions are discovered in arbitrary package order. Resolve
    # dependencies before invoking the loader, which still enforces the contract.
    from radd.kernel.loader import PluginLoadError

    known = {path: plugin for plugin, path in discovery.all_known().values()}
    ordered: list[str] = []
    seen: set[str] = set()
    while paths:
        ready = [path for path in paths if set(known[path].depends_on) <= seen]
        if not ready:
            details = {known[path].name: sorted(set(known[path].depends_on) - seen) for path in paths}
            raise PluginLoadError(f"Plugin dependencies missing or cyclic: {details}")
        for path in ready:
            ordered.append(path)
            seen.add(known[path].name)
            paths.remove(path)
    return tuple(ordered)
