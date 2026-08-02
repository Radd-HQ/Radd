"""Boot-time resolution of which plugins load (docs/plugin-platform.md §10).

`create_app` loads:
  - every **core** bootstrap plugin from `config.modules` (locked, always on);
  - every **optional** bootstrap plugin from `config.modules` (`core=False`) UNLESS
    it's explicitly DISABLED in `installed_plugins` (on by default, disableable);
  - every **installable** plugin (`config.installable_plugins`) that is ENABLED
    (off by default, enable to turn on).

A synchronous read (short-lived sync engine over the psycopg driver) so it runs
before routers mount. Defensive: if the table doesn't exist yet it behaves as "no
overrides" (everything default).
"""

from sqlalchemy import create_engine, text

from radd.config import settings

from . import discovery
from .types import PluginState


def plugin_states() -> dict[str, str]:
    """{plugin_id: state} for every installed_plugins row (empty if unavailable)."""
    try:
        engine = create_engine(settings.database_url)  # psycopg3 works sync + async
        try:
            with engine.connect() as conn:
                rows = conn.execute(text("SELECT id, state FROM installed_plugins")).all()
                return {r[0]: r[1] for r in rows}
        finally:
            engine.dispose()
    except Exception:
        return {}


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


def enabled_installable_paths() -> tuple[str, ...]:
    """Back-compat: just the ENABLED installable plugin paths."""
    states = plugin_states()
    return tuple(
        path
        for pid, (_plugin, path) in discovery.installable_plugins().items()
        if states.get(pid) == PluginState.ENABLED.value
    )
