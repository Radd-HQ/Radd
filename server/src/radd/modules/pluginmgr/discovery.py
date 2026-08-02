"""Plugin discovery — the manager's view of what exists (docs/plugin-platform.md §10).

Core plugins come from `config.modules` (always enabled, locked). Installable (non-core) plugins
come from two sources, both surfaced as `installable_plugins()`:
  - `config.installable_plugins` — in-repo builtin optional plugins (e.g. the north-star milestones);
  - **third-party `radd.plugins` entry points** — a pip/uv-installed external plugin package
    (e.g. examples/acme-notes) is discovered here with NO edit to the core config, which is what lets
    it install/enable at runtime with zero repo edits (spec 94 acceptance).
Every entry is `id → (plugin, importable module path)`.
"""

import importlib
from importlib.metadata import entry_points

from radd.config import settings
from radd.kernel import RaddPlugin

# The entry-point group an external plugin declares in its pyproject to be discovered:
#   [project.entry-points."radd.plugins"]
#   acme-notes = "acme_notes"
ENTRY_POINT_GROUP = "radd.plugins"


def _plugin_of(obj: object) -> RaddPlugin | None:
    if isinstance(obj, RaddPlugin):
        return obj
    plugin = getattr(obj, "plugin", None) or getattr(obj, "module", None)
    return plugin if isinstance(plugin, RaddPlugin) else None


def _load(path: str) -> RaddPlugin | None:
    pkg = importlib.import_module(path)
    return _plugin_of(pkg)


def entrypoint_plugins() -> dict[str, tuple[RaddPlugin, str]]:
    """External plugins advertised via the `radd.plugins` entry-point group. A broken/incompatible
    entry point is skipped (quarantined), never fatal — one bad plugin can't block discovery."""
    out: dict[str, tuple[RaddPlugin, str]] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            plugin = _plugin_of(ep.load())
        except Exception:  # noqa: BLE001 — discovery must survive a broken third-party package
            continue
        if plugin is not None:
            # The module part of the entry point value ("acme_notes" or "acme_notes:plugin").
            out[plugin.id] = (plugin, ep.value.split(":", 1)[0].strip())
    return out


def core_plugins() -> dict[str, tuple[RaddPlugin, str]]:
    out: dict[str, tuple[RaddPlugin, str]] = {}
    for path in settings.modules:
        plugin = _load(path)
        if plugin is not None:
            out[plugin.id] = (plugin, path)
    return out


def installable_plugins() -> dict[str, tuple[RaddPlugin, str]]:
    """Non-core plugins the manager may install/enable, keyed by plugin id — in-repo optional
    plugins (config) plus discovered third-party entry-point plugins."""
    out: dict[str, tuple[RaddPlugin, str]] = {}
    for path in settings.installable_plugins:
        plugin = _load(path)
        if plugin is not None:
            out[plugin.id] = (plugin, path)
    # Entry-point plugins layer on top; a config entry with the same id wins (in-repo is canonical).
    for pid, entry in entrypoint_plugins().items():
        out.setdefault(pid, entry)
    return out


def all_known() -> dict[str, tuple[RaddPlugin, str]]:
    return {**core_plugins(), **installable_plugins()}


def path_for(plugin_id: str) -> str | None:
    entry = all_known().get(plugin_id)
    return entry[1] if entry else None
