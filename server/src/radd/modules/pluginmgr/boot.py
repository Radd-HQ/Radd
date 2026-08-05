"""Boot-time resolution of which plugins load (docs/plugin-platform.md §10).

`create_app` loads:
  - every **core** bootstrap plugin from `config.modules` (locked, always on);
  - every **optional** bootstrap plugin from `config.modules` (`core=False`) UNLESS
    it's explicitly DISABLED in `installed_plugins` (on by default, disableable);
  - every **installable** plugin (`config.installable_plugins`) that is ENABLED
    (off by default, enable to turn on).

A synchronous read (short-lived sync engine over the psycopg driver) so it runs
before routers mount. Defensive ONLY for the fresh-database case: a missing
`installed_plugins` table reads as "no overrides". Every other failure raises —
answering "no overrides" on a transient DB error would silently change which
plugins load (the spec-104 lesson: a swallowed error here means "disable
changed nothing"), and a boot that cannot read its plugin state should fail
loudly and restart, not guess (RADD-873).
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
    except ProgrammingError:
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
        if plugin.core or states.get(pid) != PluginState.DISABLED.value:
            paths.append(path)
    # installable — only when enabled
    for pid, (plugin, path) in discovery.installable_plugins().items():
        if states.get(pid) == PluginState.ENABLED.value:
            paths.append(path)
    return tuple(paths)
