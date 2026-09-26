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
    """Which plugin contributed a thing, as the registry saw it register.

    Recorded here rather than on the spec because the spec is authored BY the
    plugin: a self-declared `source` could disagree with reality, and only the
    registry is in a position to know the truth.

    Deliberately just the plugin's NAME. The first cut carried a `core` flag so
    the editor's insert menu could group "built in" apart from "from a plugin"
    (RADD-748) — but `core` means "cannot be disabled", not "ships with Radd",
    and `pages` is itself `core=False`, so first-party extensions landed under a
    plugin heading. The deeper point is that development rule 1 says everything
    IS a plugin, so a built-in/plugin split was fighting the architecture to
    produce a distinction that is not real. Grouping by contributor is both
    simpler and true.
    """

    plugin: str


@dataclass
class KernelRegistries:
    plugins: dict[str, RaddPlugin] = field(default_factory=dict)
    entities: dict[str, EntitySpec] = field(default_factory=dict)
    event_types: dict[str, EventTypeSpec] = field(default_factory=dict)
    #: entity type -> how to describe it in an event payload (RADD-923). Read by
    #: `events.emit` to expand `subjects={"item": id}` into a canonical ref.
    entity_refs: dict[str, EntityRefSpec] = field(default_factory=dict)
    entity_links: dict[str, EntityLinkSpec] = field(default_factory=dict)
    entity_link_owners: dict[str, RaddPlugin] = field(default_factory=dict)
    permissions: dict[str, PermissionSpec] = field(default_factory=dict)
    #: RADD-891: scalar cascade settings, keyed like `settings.types.SettingKey`'s
    #: values — the inversion of that module's old hardcoded catalog dict.
    settings: dict[str, SettingSpec] = field(default_factory=dict)
    #: (resource, key) -> what @key MEANS for that resource's rows (RADD-823).
    relations: dict[tuple[str, str], RelationSpec] = field(default_factory=dict)
    #: base atom -> the resource whose relations qualify it (RADD-844). Default
    #: is the atom's own prefix; a CREATE-shaped atom whose row does not exist
    #: yet may declare its PARENT — `comment.write@participant` reads "write
    #: comments on ITEMS shared with them", so its qualifier resolves against
    #: the item relations, in validation and at the gate alike.
    relation_domains: dict[str, str] = field(default_factory=dict)
    #: RADD-818: spec-92 access resources — the SIXTEENTH contribution kind,
    #: typed loosely (the spec class lives in modules/access; kernel purity
    #: forbids importing it). modules/access reads THROUGH this dict, so a
    #: plugin's resource type is withdrawn with its plugin on disable.
    access_resources: dict[str, object] = field(default_factory=dict)
    crud_resources: dict[str, CrudResourceSpec] = field(default_factory=dict)
    #: RADD-892, the aggregation inversion — three registries whose consumer used
    #: to hold the list instead: /auth/me's nav facts, the scope kinds a role
    #: grant binds to, and the rows that die with a project.
    nav_facts: dict[str, NavFactSpec] = field(default_factory=dict)
    grant_scopes: dict[str, GrantScopeSpec] = field(default_factory=dict)
    #: RADD-937: why an actor can SEE a project without being granted it.
    #: Read blind by the visibility resolver, which names no contributor.
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
    #: Which plugin contributed each page extension (RADD-748). The registry is
    #: the only thing that knows — the spec is authored BY the plugin, so a
    #: `source` field on it would be self-declared and could disagree with
    #: reality. Kept beside the specs rather than inside them for that reason.
    page_extension_sources: dict[str, ContributionSource] = field(default_factory=dict)
    #: A LIST, not a dict: several modules cascade off the same parent event.
    cascades: list[CascadeSpec] = field(default_factory=list)  # RADD-745
    tasks: dict[str, TaskSpec] = field(default_factory=dict)
    consumer_names: set[str] = field(default_factory=set)  # RADD-1093
    integrations: dict[tuple[str, str], IntegrationSpec] = field(default_factory=dict)
    nav: list[NavItemSpec] = field(default_factory=list)
    # name -> absolute path of the plugin's built UI bundle dir (`<plugin_dir>/ui/dist`), for the
    # plugins that ship a federated UI (spec 94). The backend serves /plugins/<name>/* from here, so
    # a plugin's UI lives IN the plugin's own directory (no central assets dir).
    plugin_ui_dirs: dict[str, str] = field(default_factory=dict)

    def clear(self) -> None:
        for f in (
            self.plugins, self.entities, self.event_types, self.entity_refs, self.permissions,
            self.entity_links, self.entity_link_owners,
            self.settings, self.relations, self.relation_domains, self.access_resources,
            self.row_guards,
            self.crud_resources, self.nav_facts, self.grant_scopes, self.project_relations, self.project_purges,
            self.capabilities, self.tasks, self.consumer_names,
            self.integrations, self.plugin_ui_dirs, self.slq_fields,
            self.view_types, self.widget_types, self.mcp_tools, self.page_extensions,
            self.automation_nodes, self.trigger_kinds, self.token_providers, self.automation_templates,
            self.notification_kinds, self.searchables, self.record_local_entities,
            self.page_extension_sources,
        ):
            f.clear()
        self.cascades.clear()
        self.nav.clear()

    # --- registration (called by the loader per plugin) ---
    def register_plugin(self, plugin: RaddPlugin) -> None:
        from .entity_links import contributed_links

        links = contributed_links(plugin)
        # Validate before changing any registry: a failed activation must not
        # steal another owner's link or leave this plugin partially registered.
        for link in links:
            previous = self.entity_link_owners.get(link.entity_type)
            if previous is not None and previous.id != plugin.id:
                raise ValueError(f"entity link {link.entity_type!r} already belongs to {previous.name!r}")
        for key, owner in list(self.entity_link_owners.items()):
            if owner.id == plugin.id:
                self.entity_links.pop(key, None)
                self.entity_link_owners.pop(key, None)
        for link in links:
            self.entity_links[link.entity_type] = link
            self.entity_link_owners[link.entity_type] = plugin
        self.plugins[plugin.id] = plugin
        for e in plugin.entities:
            self.entities[e.key] = e
        for et in plugin.event_types:
            self.event_types[et.event_type] = et
        for consumer_name in plugin.consumer_names:
            self.consumer_names.add(consumer_name)
        for er in plugin.entity_refs:
            self.entity_refs[er.entity_type] = er
        for p in plugin.permissions:
            self.permissions[p.key] = p
        for s in plugin.settings_keys:
            self.settings[s.key] = s
        for r in plugin.relations:
            self.relations[(r.resource, r.key)] = r
        for g in plugin.row_guards:
            self.row_guards[g.resource] = g
        for atom, resource in plugin.relation_domains:
            self.relation_domains[atom] = resource
        for ar in plugin.access_resources:
            self.access_resources[ar.resource_type] = ar  # type: ignore[attr-defined]
        for c in plugin.crud_resources:
            self.crud_resources[c.key] = c
        for nf in plugin.nav_facts:
            self.nav_facts[nf.key] = nf
        for gs in plugin.grant_scopes:
            self.grant_scopes[gs.key] = gs
        for pr in plugin.project_relations:
            self.project_relations[pr.key] = pr
        for pp in plugin.project_purges:
            self.project_purges[pp.name] = pp
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
        for node in plugin.automation_nodes:
            self.automation_nodes[node.key] = node
        for kind in plugin.trigger_kinds:
            self.trigger_kinds[kind.key] = kind
        for provider in plugin.token_providers:
            self.token_providers[provider.root] = provider
        for template in plugin.automation_templates:
            self.automation_templates[template.key] = template
        for kind in plugin.notification_kinds:
            self.notification_kinds[kind.key] = kind
        for searchable in plugin.searchables:
            self.searchables[searchable.entity_type] = searchable
        self.record_local_entities.update(plugin.record_local_entities)
        for px in plugin.page_extensions:
            self.page_extensions[px.name] = px
            self.page_extension_sources[px.name] = ContributionSource(plugin=plugin.name)
        if plugin.cascades is not None:
            for cascade in plugin.cascades():
                if cascade not in self.cascades:
                    self.cascades.append(cascade)
        for t in plugin.tasks:
            self.tasks[t.name] = t
        for ig in plugin.integrations:
            self.integrations[(ig.socket, ig.name)] = ig
        if plugin.ui is not None:
            keys = {n.key for n in plugin.ui.nav}
            self.nav[:] = [n for n in self.nav if n.key not in keys]  # dedupe re-registers
            self.nav.extend(plugin.ui.nav)

    def unregister_plugin(self, plugin: RaddPlugin) -> None:
        """Remove a plugin's contributions (runtime disable) — its nav, event types,
        atoms, resources, capabilities, integrations, and entities stop being served."""
        # A delayed cleanup from a replaced generation owns no current state.
        if self.plugins.get(plugin.id) is not plugin:
            return
        self.plugins.pop(plugin.id, None)
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
            self.entities.pop(e.key, None)
            self.crud_resources.pop(e.key, None)
            self.entity_refs.pop(e.key, None)
            from .entities import _event_types, _project_purge
            for event in _event_types(e):
                self.event_types.pop(event.event_type, None)
            if e.project_scoped:
                self.project_purges.pop(_project_purge(e).name, None)
            self.searchables.pop(e.key, None)  # RADD-1327: derived at register
        for et in plugin.event_types:
            self.event_types.pop(et.event_type, None)
        for er in plugin.entity_refs:
            self.entity_refs.pop(er.entity_type, None)
        for p in plugin.permissions:
            self.permissions.pop(p.key, None)
        for s in plugin.settings_keys:
            self.settings.pop(s.key, None)
        for r in plugin.relations:
            self.relations.pop((r.resource, r.key), None)
        for g in plugin.row_guards:
            self.row_guards.pop(g.resource, None)
        for atom, _resource in plugin.relation_domains:
            self.relation_domains.pop(atom, None)
        for ar in plugin.access_resources:
            self.access_resources.pop(ar.resource_type, None)  # type: ignore[attr-defined]
        for c in plugin.crud_resources:
            self.crud_resources.pop(c.key, None)
        for nf in plugin.nav_facts:
            self.nav_facts.pop(nf.key, None)
        for gs in plugin.grant_scopes:
            self.grant_scopes.pop(gs.key, None)
        for pr in plugin.project_relations:
            self.project_relations.pop(pr.key, None)
        for pp in plugin.project_purges:
            self.project_purges.pop(pp.name, None)
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
        for node in plugin.automation_nodes:
            self.automation_nodes.pop(node.key, None)
        for kind in plugin.trigger_kinds:
            self.trigger_kinds.pop(kind.key, None)
        for provider in plugin.token_providers:
            self.token_providers.pop(provider.root, None)
        for template in plugin.automation_templates:
            self.automation_templates.pop(template.key, None)
        for kind in plugin.notification_kinds:
            self.notification_kinds.pop(kind.key, None)
        for searchable in plugin.searchables:
            self.searchables.pop(searchable.entity_type, None)
        self.record_local_entities.difference_update(plugin.record_local_entities)
        for px in plugin.page_extensions:
            self.page_extensions.pop(px.name, None)
            self.page_extension_sources.pop(px.name, None)
        if plugin.cascades is not None:
            for cascade in plugin.cascades():
                if cascade in self.cascades:
                    self.cascades.remove(cascade)
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

    def relations_for(self, resource: str) -> dict[str, RelationSpec]:
        """Every relation registered for one resource, keyed by qualifier (RADD-823)."""
        return {key: spec for (res, key), spec in self.relations.items() if res == resource}

    def relation_domain(self, base_atom: str) -> str:
        """The resource whose relations qualify `base_atom` (RADD-844): the
        declared override, else the atom's own prefix."""
        return self.relation_domains.get(base_atom, base_atom.partition(".")[0])

    def project_purge_tables(self) -> tuple[str, ...]:
        """Every table a dying project's rows must be deleted from, in an order
        the foreign keys survive (RADD-892).

        Flattened here rather than at the call site so the ordering rule — spec
        `order` first, then the order a spec lists its own tables — is stated
        once. Deduped because two modules may legitimately name the same table
        during a hand-off.
        """
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
        `event_types` OR derived from one of its EntitySpecs (RADD-1371: the
        automation catalog read only the former, so any EntitySpec plugin's
        `<entity>.created` trigger had no owner and the catalog 500'd)."""
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
    registries.integrations[(spec.socket, spec.name)] = spec
    return spec
