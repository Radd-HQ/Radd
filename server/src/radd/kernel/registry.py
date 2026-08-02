"""The kernel contribution registries — one dict per contribution kind, populated
by the loader and read by exactly one generic consumer. No consumer names a plugin
(docs/plugin-platform.md §4). This is the `access.registry` pattern, generalized.

The registry is a process-global singleton (`registries`). The loader calls
`register_plugin` for each loaded plugin, which fans the manifest fields out into
the per-kind dicts. Consumers (automations, /capabilities, the nav manifest) read
these dicts blind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .plugin import RaddPlugin
from .specs import (
    CapabilitySpec,
    ConsumerSpec,
    CrudResourceSpec,
    EntitySpec,
    EventTypeSpec,
    IntegrationSpec,
    McpToolSpec,
    NavItemSpec,
    PageExtensionSpec,
    PermissionSpec,
    SlqFieldSpec,
    ViewTypeSpec,
    WidgetTypeSpec,
    TaskSpec,
)


@dataclass
class KernelRegistries:
    plugins: dict[str, RaddPlugin] = field(default_factory=dict)
    entities: dict[str, EntitySpec] = field(default_factory=dict)
    event_types: dict[str, EventTypeSpec] = field(default_factory=dict)
    permissions: dict[str, PermissionSpec] = field(default_factory=dict)
    crud_resources: dict[str, CrudResourceSpec] = field(default_factory=dict)
    capabilities: dict[str, CapabilitySpec] = field(default_factory=dict)
    slq_fields: dict[str, SlqFieldSpec] = field(default_factory=dict)  # plugin SLQ query fields
    view_types: dict[str, ViewTypeSpec] = field(default_factory=dict)  # plugin saved-view types
    widget_types: dict[str, WidgetTypeSpec] = field(default_factory=dict)  # plugin dashboard widgets
    mcp_tools: dict[str, McpToolSpec] = field(default_factory=dict)  # plugin MCP tools (RADD-640)
    page_extensions: dict[str, PageExtensionSpec] = field(default_factory=dict)  # RADD-709
    tasks: dict[str, TaskSpec] = field(default_factory=dict)
    consumers: dict[str, ConsumerSpec] = field(default_factory=dict)
    integrations: dict[tuple[str, str], IntegrationSpec] = field(default_factory=dict)
    nav: list[NavItemSpec] = field(default_factory=list)
    entity_routers: list = field(default_factory=list)  # auto-generated CRUD routers
    # name -> absolute path of the plugin's built UI bundle dir (`<plugin_dir>/ui/dist`), for the
    # plugins that ship a federated UI (spec 94). The backend serves /plugins/<name>/* from here, so
    # a plugin's UI lives IN the plugin's own directory (no central assets dir).
    plugin_ui_dirs: dict[str, str] = field(default_factory=dict)

    def clear(self) -> None:
        for f in (
            self.plugins, self.entities, self.event_types, self.permissions,
            self.crud_resources, self.capabilities, self.tasks, self.consumers,
            self.integrations, self.plugin_ui_dirs, self.slq_fields,
            self.view_types, self.widget_types, self.mcp_tools, self.page_extensions,
        ):
            f.clear()
        self.nav.clear()
        self.entity_routers.clear()

    # --- registration (called by the loader per plugin) ---
    def register_plugin(self, plugin: RaddPlugin) -> None:
        self.plugins[plugin.id] = plugin
        for e in plugin.entities:
            self.entities[e.key] = e
        for et in plugin.event_types:
            self.event_types[et.event_type] = et
        for p in plugin.permissions:
            self.permissions[p.key] = p
        for c in plugin.crud_resources:
            self.crud_resources[c.key] = c
        for cap in plugin.capabilities:
            self.capabilities[cap.key] = cap
        for sf in plugin.slq_fields:
            self.slq_fields[sf.name] = sf
        for vt in plugin.view_types:
            self.view_types[vt.key] = vt
        for wt in plugin.widget_types:
            self.widget_types[wt.key] = wt
        for mt in plugin.mcp_tools:
            self.mcp_tools[mt.name] = mt
        for px in plugin.page_extensions:
            self.page_extensions[px.name] = px
        for t in plugin.tasks:
            self.tasks[t.name] = t
        for con in plugin.consumers:
            self.consumers[con.name] = con
        for ig in plugin.integrations:
            self.integrations[(ig.socket, ig.name)] = ig
        if plugin.ui is not None:
            keys = {n.key for n in plugin.ui.nav}
            self.nav[:] = [n for n in self.nav if n.key not in keys]  # dedupe re-registers
            self.nav.extend(plugin.ui.nav)

    def unregister_plugin(self, plugin: RaddPlugin) -> None:
        """Remove a plugin's contributions (runtime disable) — its nav, event types,
        atoms, resources, capabilities, integrations, and entities stop being served."""
        self.plugins.pop(plugin.id, None)
        for e in plugin.entities:
            self.entities.pop(e.key, None)
        for et in plugin.event_types:
            self.event_types.pop(et.event_type, None)
        for p in plugin.permissions:
            self.permissions.pop(p.key, None)
        for c in plugin.crud_resources:
            self.crud_resources.pop(c.key, None)
        for cap in plugin.capabilities:
            self.capabilities.pop(cap.key, None)
        for sf in plugin.slq_fields:
            self.slq_fields.pop(sf.name, None)
        for vt in plugin.view_types:
            self.view_types.pop(vt.key, None)
        for wt in plugin.widget_types:
            self.widget_types.pop(wt.key, None)
        for mt in plugin.mcp_tools:
            self.mcp_tools.pop(mt.name, None)
        for px in plugin.page_extensions:
            self.page_extensions.pop(px.name, None)
        for con in plugin.consumers:
            self.consumers.pop(con.name, None)
        for ig in plugin.integrations:
            self.integrations.pop((ig.socket, ig.name), None)
        if plugin.ui is not None:
            keys = {n.key for n in plugin.ui.nav}
            self.nav[:] = [n for n in self.nav if n.key not in keys]
        self.plugin_ui_dirs.pop(plugin.name, None)

    def register_plugin_ui_dir(self, plugin: RaddPlugin, module: object) -> None:
        """Record where a plugin's built UI bundle lives — `<dir of the plugin's module>/ui/dist`.
        Called by the loader/hot-mount with the imported plugin module, so serving works uniformly
        for builtin plugins (`server/.../modules/<n>/ui/dist`) and external ones (packaged the same
        way in their own module)."""
        if plugin.ui is None or not plugin.ui.remote:
            return
        module_file = getattr(module, "__file__", None)
        if module_file:
            self.plugin_ui_dirs[plugin.name] = str(Path(module_file).resolve().parent / "ui" / "dist")

    # --- reads (the generic consumers) ---
    def triggers(self) -> dict[str, EventTypeSpec]:
        """Event types that are automation triggers — chokepoint-1 inversion."""
        return {k: v for k, v in self.event_types.items() if v.trigger}

    def integration(self, socket: str, name: str) -> IntegrationSpec | None:
        return self.integrations.get((socket, name))

    def providers(self, socket: str) -> dict[str, IntegrationSpec]:
        return {n: ig for (s, n), ig in self.integrations.items() if s == socket and not ig.consumes}


# Process-global singleton.
registries = KernelRegistries()


# --- module-level convenience for import-time registration by plugins ---
def register_event_type(spec: EventTypeSpec) -> EventTypeSpec:
    registries.event_types[spec.event_type] = spec
    return spec


def register_permission(spec: PermissionSpec) -> PermissionSpec:
    registries.permissions[spec.key] = spec
    return spec


def register_crud_resource(spec: CrudResourceSpec) -> CrudResourceSpec:
    registries.crud_resources[spec.key] = spec
    return spec


def register_capability(spec: CapabilitySpec) -> CapabilitySpec:
    registries.capabilities[spec.key] = spec
    return spec


def register_integration(spec: IntegrationSpec) -> IntegrationSpec:
    registries.integrations[(spec.socket, spec.name)] = spec
    return spec
