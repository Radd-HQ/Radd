"""The plugin loader.

Imports each configured plugin package, accepts either the `plugin: RaddPlugin`
export or the pre-kernel `module:` export, verifies `depends_on` + `api_version`
compat, registers its contributions into the kernel registries, and returns the
ordered list. `import_models` is unchanged (imports each `<path>.models` so
Base.metadata is complete for the app + Alembic).
"""

import importlib

from .plugin import KERNEL_API_VERSION, RaddPlugin
from .registry import registries


class PluginLoadError(Exception):
    pass


def _api_compatible(plugin_api: str, kernel_api: str) -> bool:
    """Semver major-compat gate (§9): a plugin loads iff its api_version's major
    matches the kernel's. Minors/patches are backward-compatible by contract."""
    try:
        return plugin_api.split(".")[0] == kernel_api.split(".")[0]
    except (AttributeError, IndexError):
        return False


def load_plugins(paths: tuple[str, ...]) -> list[RaddPlugin]:
    plugins: list[RaddPlugin] = []
    seen: set[str] = set()
    registries.clear()
    for path in paths:
        pkg = importlib.import_module(path)
        plugin = getattr(pkg, "plugin", None) or getattr(pkg, "module", None)
        if not isinstance(plugin, RaddPlugin):
            raise PluginLoadError(f"{path} does not expose `plugin: RaddPlugin` (or `module`)")
        if not _api_compatible(plugin.api_version, KERNEL_API_VERSION):
            raise PluginLoadError(
                f"plugin {plugin.id!r} targets api_version {plugin.api_version}, "
                f"incompatible with kernel {KERNEL_API_VERSION}"
            )
        missing = [dep for dep in plugin.depends_on if dep not in seen]
        if missing:
            raise PluginLoadError(
                f"plugin {plugin.id!r} depends on {missing} — order/enable them first"
            )
        # `name` is the stable enable key (matches depends_on which use module names).
        seen.add(plugin.name)
        registries.register_plugin(plugin)
        # Record where this plugin's built UI bundle lives (`<plugin dir>/ui/dist`) so the backend
        # serves /plugins/<name>/* from the plugin's OWN directory (spec 94 colocation).
        registries.register_plugin_ui_dir(plugin, pkg)
        # Auto-wire declared entities: build the model + register CRUD-resource
        # atoms + created/updated/deleted event types + a generated CRUD router
        # (the payoff of mediation — the plugin writes no model/router/RBAC code).
        if plugin.entities:
            from . import entities as kentities

            for spec in plugin.entities:
                kentities.register_entity(spec)
                registries.entity_routers.append(kentities.crud_router(spec))
        plugins.append(plugin)
    _check_subjects(plugins)
    return plugins


def _check_subjects(plugins: list[RaddPlugin]) -> None:
    """Every declared event subject must have a registered `EntityRefSpec`
    (RADD-923), and every contributed action node's subject too.

    Checked after the whole set has loaded, not per plugin: the ref may be
    contributed by a plugin listed later, and ordering is `depends_on`'s job, not
    this check's.

    Boot is the cheapest place to find this. An event promising a subject nothing
    can resolve produces an automation that saves cleanly, enables cleanly and
    then does nothing at 3am — the failure mode this whole seam exists to remove,
    so it must not be reintroduced by the seam itself.
    """
    known = set(registries.entity_refs)
    problems: list[str] = []
    for plugin in plugins:
        for event in plugin.event_types:
            for subject in event.subjects:
                if subject not in known:
                    problems.append(
                        f"{plugin.id!r}: event {event.event_type!r} names subject "
                        f"{subject!r}, which no plugin describes"
                    )
        for node in plugin.automation_nodes:
            if node.kind == "action" and node.subject and node.subject not in known:
                problems.append(
                    f"{plugin.id!r}: action node {node.key!r} acts on subject "
                    f"{node.subject!r}, which no plugin describes"
                )
    if problems:
        raise PluginLoadError(
            "unresolvable event subjects — register an EntityRefSpec for each: "
            + "; ".join(problems)
        )


def import_models(paths: tuple[str, ...]) -> None:
    """Import each enabled plugin's models so Base.metadata is complete (app + Alembic)."""
    for path in paths:
        try:
            importlib.import_module(f"{path}.models")
        except ModuleNotFoundError as exc:
            if exc.name != f"{path}.models":
                raise

