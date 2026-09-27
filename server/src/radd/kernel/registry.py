"""The kernel contribution registries — one dict per contribution kind, filled by the
loader (`register_plugin`) and read blind by generic consumers; no consumer names a
plugin (docs/plugin-platform.md §4). `registries` is the process-global singleton."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from operator import attrgetter
from pathlib import Path

from .plugin import RaddPlugin
from .specs import (
    AutomationNodeSpec,
    TriggerKindSpec,
    TokenProviderSpec,
    AutomationTemplateSpec,
    NotificationKindSpec,
    SearchableSpec,
    RelationSpec,
    RowGuardSpec,
    CapabilitySpec,
    CascadeSpec,
    CrudResourceSpec,
    EntitySpec,
    EntityRefSpec,
    EntityLinkSpec,
    EventTypeSpec,
    GrantScopeSpec,
    ProjectRelationSpec,
    IntegrationSpec,
    McpToolSpec,
    NavFactSpec,
    NavItemSpec,
    PageExtensionSpec,
    PermissionSpec,
    ProjectPurgeSpec,
    SettingSpec,
    SlqFieldSpec,
    ViewTypeSpec,
    WidgetTypeSpec,
    TaskSpec,
)


@dataclass(frozen=True)
class ContributionSource:
    """Which plugin contributed a thing, as the registry saw it register — never
    self-declared on the spec, which the plugin authors and could get wrong."""

    plugin: str


class ContributionConflict(ValueError):
    """Two plugins contribute one keyed thing that has exactly one owner — an
    entity link, or an integration on a socket (RADD-1456). Raised BEFORE the
    registry changes, naming both, so an enable fails on its row instead of one
    plugin silently replacing the other's provider."""


#: (manifest field, registry dict, key) for every contribution kind that is a plain
#: keyed dict: registering overwrites the key, unregistering pops it. Kinds with any
#: other behaviour are handled explicitly in register_plugin/unregister_plugin
#: (integrations: a duplicate key is a ContributionConflict, never an overwrite).
_KEYED: tuple[tuple[str, str, attrgetter], ...] = (
    ("entities", "entities", attrgetter("key")),
    ("event_types", "event_types", attrgetter("event_type")),
    ("entity_refs", "entity_refs", attrgetter("entity_type")),
    ("permissions", "permissions", attrgetter("key")),
    ("settings_keys", "settings", attrgetter("key")),
    ("relations", "relations", attrgetter("resource", "key")),
    ("row_guards", "row_guards", attrgetter("resource")),
    ("access_resources", "access_resources", attrgetter("resource_type")),
    ("crud_resources", "crud_resources", attrgetter("key")),
    ("nav_facts", "nav_facts", attrgetter("key")),
    ("grant_scopes", "grant_scopes", attrgetter("key")),
    ("project_relations", "project_relations", attrgetter("key")),
    ("project_purges", "project_purges", attrgetter("name")),
    ("capabilities", "capabilities", attrgetter("key")),
    ("slq_fields", "slq_fields", attrgetter("name")),
    ("view_types", "view_types", attrgetter("key")),
    ("widget_types", "widget_types", attrgetter("key")),
    ("mcp_tools", "mcp_tools", attrgetter("name")),
    ("automation_nodes", "automation_nodes", attrgetter("key")),
    ("trigger_kinds", "trigger_kinds", attrgetter("key")),
    ("token_providers", "token_providers", attrgetter("root")),
    ("automation_templates", "automation_templates", attrgetter("key")),
    ("notification_kinds", "notification_kinds", attrgetter("key")),
    ("searchables", "searchables", attrgetter("entity_type")),
    ("page_extensions", "page_extensions", attrgetter("name")),
)


def _integration_key(spec: IntegrationSpec) -> tuple[str, str]:
    return (str(spec.socket), spec.name)


@dataclass
class KernelRegistries:
    plugins: dict[str, RaddPlugin] = field(default_factory=dict)
    entities: dict[str, EntitySpec] = field(default_factory=dict)
    event_types: dict[str, EventTypeSpec] = field(default_factory=dict)
    #: entity type -> how `events.emit` describes it in a payload (RADD-923).
    entity_refs: dict[str, EntityRefSpec] = field(default_factory=dict)
    entity_links: dict[str, EntityLinkSpec] = field(default_factory=dict)
    entity_link_owners: dict[str, RaddPlugin] = field(default_factory=dict)
    permissions: dict[str, PermissionSpec] = field(default_factory=dict)
    #: RADD-891: scalar cascade settings, keyed like `settings.types.SettingKey`'s values.
    settings: dict[str, SettingSpec] = field(default_factory=dict)
    #: (resource, key) -> what @key MEANS for that resource's rows (RADD-823).
    relations: dict[tuple[str, str], RelationSpec] = field(default_factory=dict)
    #: base atom -> the resource whose relations qualify it (RADD-844). Default is the
    #: atom's own prefix; a CREATE-shaped atom whose row does not exist yet may declare its
    #: PARENT (`comment.write@participant` resolves against the item relations).
    relation_domains: dict[str, str] = field(default_factory=dict)
    #: spec-92 access resources, typed loosely (kernel purity: the spec class lives in
    #: modules/access), so a plugin's resource type withdraws with it (RADD-818).
    access_resources: dict[str, object] = field(default_factory=dict)
    crud_resources: dict[str, CrudResourceSpec] = field(default_factory=dict)
    nav_facts: dict[str, NavFactSpec] = field(default_factory=dict)
    grant_scopes: dict[str, GrantScopeSpec] = field(default_factory=dict)
    #: RADD-937: why an actor can SEE a project without being granted it.
    project_relations: dict[str, ProjectRelationSpec] = field(default_factory=dict)
    #: resource -> the per-row admission every reader passes (spec 121).
    row_guards: dict[str, RowGuardSpec] = field(default_factory=dict)
    project_purges: dict[str, ProjectPurgeSpec] = field(default_factory=dict)
    capabilities: dict[str, CapabilitySpec] = field(default_factory=dict)
    slq_fields: dict[str, SlqFieldSpec] = field(default_factory=dict)  # plugin SLQ query fields
    view_types: dict[str, ViewTypeSpec] = field(default_factory=dict)  # plugin saved-view types
    widget_types: dict[str, WidgetTypeSpec] = field(default_factory=dict)  # plugin dashboard widgets
    mcp_tools: dict[str, McpToolSpec] = field(default_factory=dict)  # plugin MCP tools (RADD-640)
    #: Automation graph node types (spec 116 phase 2), keyed by their spec key.
    automation_nodes: dict[str, AutomationNodeSpec] = field(default_factory=dict)
    #: RADD-1323: trigger KINDS (manual/schedule/validate + any a plugin adds).
    trigger_kinds: dict[str, TriggerKindSpec] = field(default_factory=dict)
    #: RADD-1324: `{{root.field}}` vocabularies contributed by entity owners.
    token_providers: dict[str, TokenProviderSpec] = field(default_factory=dict)
    #: RADD-1316: whole automations offered as starting points.
    automation_templates: dict[str, AutomationTemplateSpec] = field(default_factory=dict)
    #: RADD-1326: notification kinds, in registration order (notify's first).
    notification_kinds: dict[str, NotificationKindSpec] = field(default_factory=dict)
    #: RADD-1327: what Cmd-K and `#` mentions can find, by entity type.
    searchables: dict[str, SearchableSpec] = field(default_factory=dict)
    #: RADD-1328: entity types the realtime hub may narrow to their item.
    record_local_entities: set[str] = field(default_factory=set)
    page_extensions: dict[str, PageExtensionSpec] = field(default_factory=dict)  # RADD-709
    #: Which plugin contributed each page extension (RADD-748).
    page_extension_sources: dict[str, ContributionSource] = field(default_factory=dict)
    #: A LIST, not a dict: several modules cascade off the same parent event.
    cascades: list[CascadeSpec] = field(default_factory=list)  # RADD-745
    tasks: dict[str, TaskSpec] = field(default_factory=dict)
    consumer_names: set[str] = field(default_factory=set)  # RADD-1093
    integrations: dict[tuple[str, str], IntegrationSpec] = field(default_factory=dict)
    #: (socket, name) -> the plugin id that provides it (RADD-1456): a second plugin on
    #: the same key is a conflict, and a single-provider socket admits one plugin at all.
    #: An import-time `register_integration` has no plugin and records no owner.
    integration_owners: dict[tuple[str, str], str] = field(default_factory=dict)
    nav: list[NavItemSpec] = field(default_factory=list)
    # name -> absolute path of the plugin's built UI bundle dir (`<plugin_dir>/ui/dist`), for the
    # plugins that ship a federated UI (spec 94). The backend serves /plugins/<name>/* from here, so
    # a plugin's UI lives IN the plugin's own directory (no central assets dir).
    plugin_ui_dirs: dict[str, str] = field(default_factory=dict)

    def clear(self) -> None:
        for f in fields(self):
            getattr(self, f.name).clear()

    # --- registration (called by the loader per plugin) ---
    def register_plugin(self, plugin: RaddPlugin) -> None:
        from .entity_links import contributed_links

        links = contributed_links(plugin)
        # Validate before changing any registry: a failed activation must not
        # steal another owner's link or leave this plugin partially registered.
        for link in links:
            previous = self.entity_link_owners.get(link.entity_type)
            if previous is not None and previous.id != plugin.id:
                raise ContributionConflict(
                    f"entity link {link.entity_type!r} already belongs to {previous.name!r}"
                )
        self._check_integrations(plugin)
        for key, owner in list(self.entity_link_owners.items()):
            if owner.id == plugin.id:
                self.entity_links.pop(key, None)
                self.entity_link_owners.pop(key, None)
        for link in links:
            self.entity_links[link.entity_type] = link
            self.entity_link_owners[link.entity_type] = plugin
        self.plugins[plugin.id] = plugin
        for plugin_field, registry, key in _KEYED:
            target = getattr(self, registry)
            for spec in getattr(plugin, plugin_field):
                target[key(spec)] = spec
        for spec in plugin.integrations:
            self.integrations[_integration_key(spec)] = spec
            self.integration_owners[_integration_key(spec)] = plugin.id
        self.consumer_names.update(plugin.consumer_names)
        for atom, resource in plugin.relation_domains:
            self.relation_domains[atom] = resource
        self.record_local_entities.update(plugin.record_local_entities)
        for px in plugin.page_extensions:
            self.page_extension_sources[px.name] = ContributionSource(plugin=plugin.name)
        if plugin.cascades is not None:
            for cascade in plugin.cascades():
                if cascade not in self.cascades:
                    self.cascades.append(cascade)
        for t in plugin.tasks:
            self.tasks[t.name] = t
        if plugin.ui is not None:
            keys = {n.key for n in plugin.ui.nav}
            self.nav[:] = [n for n in self.nav if n.key not in keys]  # dedupe re-registers
            self.nav.extend(plugin.ui.nav)

    def _owner_name(self, key: tuple[str, str]) -> str:
        owner = self.integration_owners.get(key)
        if owner is None:
            return "an import-time registration"
        return repr(self.plugins[owner].name) if owner in self.plugins else repr(owner)

    def _check_integrations(self, plugin: RaddPlugin) -> None:
        """RADD-1456: no key is provided twice, and a single-provider socket is
        provided by one plugin. Raises before anything is written."""
        from .sockets import socket_policy  # deferred: sockets imports this module

        for spec in plugin.integrations:
            key = _integration_key(spec)
            if key in self.integrations and self.integration_owners.get(key) != plugin.id:
                raise ContributionConflict(
                    f"integration {key[0]}:{key[1]} is provided by both "
                    f"{self._owner_name(key)} and {plugin.name!r}"
                )
            if socket_policy(spec.socket).single:
                others = {
                    self._owner_name(k)
                    for k in self.integrations
                    if k[0] == key[0] and self.integration_owners.get(k) != plugin.id
                }
                if others:
                    raise ContributionConflict(
                        f"socket {key[0]} takes one provider; {', '.join(sorted(others))} "
                        f"already provides it, so {plugin.name!r} cannot"
                    )

    def unregister_plugin(self, plugin: RaddPlugin) -> None:
        """Remove a plugin's contributions (runtime disable) — its nav, event types,
        atoms, resources, capabilities, integrations, and entities stop being served."""
        # A delayed cleanup from a replaced generation owns no current state.
        if self.plugins.get(plugin.id) is not plugin:
            return
        self.plugins.pop(plugin.id, None)
        for spec in plugin.integrations:
            key = _integration_key(spec)
            if self.integration_owners.get(key) == plugin.id:
                self.integrations.pop(key, None)
                self.integration_owners.pop(key, None)
        for key, owner in list(self.entity_link_owners.items()):
            if owner is plugin:
                self.entity_links.pop(key, None)
                self.entity_link_owners.pop(key, None)
        for task in plugin.tasks:
            if self.tasks.get(task.name) is task:
                self.tasks.pop(task.name)
        remaining_consumers = {name for p in self.plugins.values() for name in p.consumer_names}
        self.consumer_names.difference_update(set(plugin.consumer_names) - remaining_consumers)
        for e in plugin.entities:
            # What `entities.register_entity` derived from the spec goes with it.
            self.crud_resources.pop(e.key, None)
            self.entity_refs.pop(e.key, None)
            from .entities import _event_types, _project_purge
            for event in _event_types(e):
                self.event_types.pop(event.event_type, None)
            if e.project_scoped:
                self.project_purges.pop(_project_purge(e).name, None)
            self.searchables.pop(e.key, None)  # RADD-1327: derived at register
        for plugin_field, registry, key in _KEYED:
            target = getattr(self, registry)
            for spec in getattr(plugin, plugin_field):
                target.pop(key(spec), None)
        for atom, _resource in plugin.relation_domains:
            self.relation_domains.pop(atom, None)
        self.record_local_entities.difference_update(plugin.record_local_entities)
        for px in plugin.page_extensions:
            self.page_extension_sources.pop(px.name, None)
        if plugin.cascades is not None:
            for cascade in plugin.cascades():
                if cascade in self.cascades:
                    self.cascades.remove(cascade)
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

    def relations_for(self, resource: str) -> dict[str, RelationSpec]:
        """Every relation registered for one resource, keyed by qualifier (RADD-823)."""
        return {key: spec for (res, key), spec in self.relations.items() if res == resource}

    def relation_domain(self, base_atom: str) -> str:
        """The resource whose relations qualify `base_atom` (RADD-844): the
        declared override, else the atom's own prefix."""
        return self.relation_domains.get(base_atom, base_atom.partition(".")[0])

    def project_purge_tables(self) -> tuple[str, ...]:
        """Every table a dying project's rows must be deleted from, in an order the foreign
        keys survive: spec `order`, then each spec's own table order; deduped, since two
        modules may name one table during a hand-off (RADD-892)."""
        tables: list[str] = []
        for spec in sorted(self.project_purges.values(), key=lambda s: (s.order, s.name)):
            for table in spec.tables:
                if table not in tables:
                    tables.append(table)
        return tuple(tables)

    def cascades_for(self, event_type: str) -> list[CascadeSpec]:
        """Every registered cleanup for a parent event (RADD-745)."""
        return [c for c in self.cascades if c.parent_event == event_type]

    # --- reads (the generic consumers) ---
    def triggers(self) -> dict[str, EventTypeSpec]:
        """Event types that are automation triggers — chokepoint-1 inversion."""
        return {k: v for k, v in self.event_types.items() if v.trigger}

    def event_owners(self) -> dict[str, str]:
        """Which plugin contributed each registered event type — declared in its
        `event_types` OR derived from one of its EntitySpecs (RADD-1371)."""
        from .entities import _event_types

        owners: dict[str, str] = {}
        for plugin in self.plugins.values():
            for entity in plugin.entities:
                for event in _event_types(entity):
                    owners.setdefault(str(event.event_type), plugin.name)
            for event in plugin.event_types:
                owners[str(event.event_type)] = plugin.name
        return owners

    def integration(self, socket: str, name: str) -> IntegrationSpec | None:
        return self.integrations.get((socket, name))

    def providers(self, socket: str) -> dict[str, IntegrationSpec]:
        """A socket's providers in REGISTRATION order (the dict keeps insertion order),
        so a consumer that iterates gets the load order, never an arbitrary one."""
        return {n: ig for (s, n), ig in self.integrations.items() if s == socket}


# Process-global singleton.
registries = KernelRegistries()


# --- module-level convenience for import-time registration by plugins ---
def register_event_type(spec: EventTypeSpec) -> EventTypeSpec:
    registries.event_types[spec.event_type] = spec
    return spec


def register_permission(spec: PermissionSpec) -> PermissionSpec:
    registries.permissions[spec.key] = spec
    return spec


def register_relation_domain(base_atom: str, resource: str) -> None:
    """Declare whose relations qualify `base_atom` (RADD-844) — import-time
    like register_relation; list it on the plugin manifest too so hot
    enable/disable survives the loader's clear()."""
    registries.relation_domains[base_atom] = resource


def register_row_guard(spec: RowGuardSpec) -> RowGuardSpec:
    """Register the per-row admission for one resource (spec 121) — the
    `register_relation` shape, and listed on the manifest for the same reason."""
    registries.row_guards[spec.resource] = spec
    return spec


def register_relation(spec: RelationSpec) -> RelationSpec:
    """Register what a relation qualifier MEANS for one resource's rows
    (RADD-823). Module-level like register_cascade: the natural caller is the
    owning module's import, beside the model whose columns the predicates read."""
    registries.relations[(spec.resource, spec.key)] = spec
    return spec


def register_crud_resource(spec: CrudResourceSpec) -> CrudResourceSpec:
    registries.crud_resources[spec.key] = spec
    return spec


def register_capability(spec: CapabilitySpec) -> CapabilitySpec:
    registries.capabilities[spec.key] = spec
    return spec


def register_integration(spec: IntegrationSpec) -> IntegrationSpec:
    """Import-time registration with no owning plugin (tests, tooling). A key that
    is already provided is a conflict here too — never a silent replacement."""
    key = _integration_key(spec)
    if key in registries.integrations:
        raise ContributionConflict(
            f"integration {key[0]}:{key[1]} is already provided by {registries._owner_name(key)}"
        )
    registries.integrations[key] = spec
    return spec
