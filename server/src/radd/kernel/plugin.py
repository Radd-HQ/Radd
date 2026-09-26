"""The plugin contract — `RaddPlugin`, the manifest of declarations the loader aggregates
into kernel registries (docs/plugin-platform.md §4)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any, get_origin

from fastapi import APIRouter, Request, Response

from .specs import (
    EntityRefSpec,
    EntityLinkSpec,
    AutomationNodeSpec,
    TriggerKindSpec,
    TokenProviderSpec,
    AutomationTemplateSpec,
    NotificationKindSpec,
    SearchableSpec,
    CapabilitySpec,
    CrudResourceSpec,
    EntitySpec,
    EventTypeSpec,
    GrantScopeSpec,
    ProjectRelationSpec,
    IntegrationSpec,
    CascadeSpec,
    McpToolSpec,
    NavFactSpec,
    PageExtensionSpec,
    PermissionSpec,
    PluginUiManifest,
    ProjectPurgeSpec,
    SettingSpec,
    RelationSpec,
    RowGuardSpec,
    SlqFieldSpec,
    TaskSpec,
    ViewTypeSpec,
    WidgetTypeSpec,
)

ExceptionHandler = Callable[[Request, Any], Response | Awaitable[Response]]
OpenApiAugmentor = Callable[[dict[str, Any]], None]
StartupHook = Callable[[], Awaitable[None]]

# The kernel SDK version plugins target (§9). Loader refuses an incompatible major.
KERNEL_API_VERSION = "1.0"


class ConsumerResume(StrEnum):
    """Where an event consumer continues when its plugin is (re-)enabled (RADD-1372)."""

    #: Keep the cursor and catch up on everything emitted while the plugin was
    #: off — an index or projection that must converge (search, embeddings).
    #: The default for every consumer a plugin does not declare otherwise.
    CURSOR = "cursor"
    #: Jump to the stream head and skip what happened while the plugin was off.
    #: For consumers that DELIVER outside the instance (a requester reply, a
    #: survey): mail about a weeks-old event is worse than none.
    HEAD = "head"


@dataclass(frozen=True)
class RaddPlugin:
    """A feature, declared. Identity + lifecycle + a manifest of contributions.

    `name` doubles as `id` when `id` is unset, so the minimal
    `RaddPlugin(name=…, description=…, routers=…)` form still constructs.
    """

    name: str
    description: str = ""

    # identity & lifecycle
    id: str = ""  # stable, e.g. "radd.slas"; defaults to `name`
    version: str = "0.0.0"
    api_version: str = KERNEL_API_VERSION
    core: bool = True  # reclassified builtins are core (non-disableable); externals set False
    #: RADD-1290: a non-core BUILTIN with no stored state loads when this is
    #: True. An example plugin (milestones) sets False so a fresh instance's nav
    #: carries only real features; enabling it writes an ENABLED row.
    enabled_by_default: bool = True
    depends_on: tuple[str, ...] = ()  # other plugin names that must load first
    #: Cross-module imports the loader must NOT order by (RADD-885): deferred reverse
    #: reaches. tests/test_module_contracts.py requires every `radd.modules.X` import to
    #: appear in depends_on OR here.
    weak_depends: tuple[str, ...] = ()
    # --- contributions (each → a kernel registry) ---
    #: Offset-tracked event-consumer names this plugin runs (RADD-1093) — THE roster
    #: consumer_status trusts: an offset row matching none reads RETIRED, not stalled.
    #: Declared even for worker-only consumers, so a web replica never mistakes off-duty
    #: for retired.
    consumer_names: tuple[str, ...] = ()
    routers: tuple[APIRouter, ...] = ()
    entities: tuple[EntitySpec, ...] = ()
    event_types: tuple[EventTypeSpec, ...] = ()
    #: How this plugin's entities describe themselves inside an event payload
    #: (RADD-923). Declared once; the kernel uses it whenever ANY module names
    #: this entity as an event subject, so nobody hand-builds the shape.
    entity_refs: tuple[EntityRefSpec, ...] = ()
    tasks: tuple[TaskSpec, ...] = ()
    settings_keys: tuple[SettingSpec, ...] = ()  # scalar cascade settings this plugin owns (RADD-891)
    permissions: tuple[PermissionSpec, ...] = ()
    crud_resources: tuple[CrudResourceSpec, ...] = ()
    relations: tuple[RelationSpec, ...] = ()  # @own/@team qualifiers for this plugin's rows (RADD-823)
    #: Spec 121 — the per-row admission every reader of this plugin's rows passes.
    row_guards: tuple[RowGuardSpec, ...] = ()
    #: base atom -> resource whose relations qualify it (RADD-844) — for a
    #: CREATE-shaped atom gated against its PARENT (comment.write -> item).
    relation_domains: tuple[tuple[str, str], ...] = ()
    access_resources: tuple[Any, ...] = ()
    #: RADD-892 — facts this plugin owns and a generic consumer aggregates:
    #: whether its nav area is worth offering, the grant scope it defines, and
    #: which of its tables die with a project.
    nav_facts: tuple[NavFactSpec, ...] = ()
    grant_scopes: tuple[GrantScopeSpec, ...] = ()
    #: RADD-937 — what makes a project visible without a grant on it.
    project_relations: tuple[ProjectRelationSpec, ...] = ()
    project_purges: tuple[ProjectPurgeSpec, ...] = ()
    capabilities: tuple[CapabilitySpec, ...] = ()
    slq_fields: tuple[SlqFieldSpec, ...] = ()  # custom SLQ query fields (e.g. `note ~ "x"`)
    view_types: tuple[ViewTypeSpec, ...] = ()  # custom saved-view types
    widget_types: tuple[WidgetTypeSpec, ...] = ()  # custom dashboard widget types
    mcp_tools: tuple[McpToolSpec, ...] = ()  # MCP tools (RADD-640; filtered + enforced by the kernel)
    #: Automation graph node types (spec 116 phase 2) — what the canvas palette
    #: offers and what the executor knows how to run.
    automation_nodes: tuple[AutomationNodeSpec, ...] = ()
    #: Trigger kinds (RADD-1323) — a button, a clock, a webhook endpoint.
    trigger_kinds: tuple[TriggerKindSpec, ...] = ()
    #: `{{root.field}}` template vocabularies (RADD-1324).
    token_providers: tuple[TokenProviderSpec, ...] = ()
    #: Whole automations offered as starting points (RADD-1316).
    automation_templates: tuple[AutomationTemplateSpec, ...] = ()
    #: Notification kinds (RADD-1326) — matrix rows, and for a plugin the events
    #: that produce them.
    notification_kinds: tuple[NotificationKindSpec, ...] = ()
    #: Cmd-K / `#`-mention searchables (RADD-1327).
    searchables: tuple[SearchableSpec, ...] = ()
    #: RADD-1328: event entity types whose effects stay on ONE item record (a
    #: comment, a worklog, a link) — the realtime hub narrows their refresh to
    #: that item instead of invalidating every open list.
    record_local_entities: tuple[str, ...] = ()
    page_extensions: tuple[PageExtensionSpec, ...] = ()  # page fenced blocks (RADD-709)
    #: Rows that die with a parent (RADD-745). A FACTORY: the set derives from bindings
    #: other modules register at import time, after this manifest is constructed.
    cascades: Callable[[], tuple[CascadeSpec, ...]] | None = None
    integrations: tuple[IntegrationSpec, ...] = ()
    ui: PluginUiManifest | None = None

    # kept from the pre-kernel module contract
    exception_handlers: tuple[tuple[type[Exception], ExceptionHandler], ...] = ()
    openapi_augmentors: tuple[OpenApiAugmentor, ...] = ()
    on_startup: tuple[StartupHook, ...] = ()
    on_shutdown: tuple[StartupHook, ...] = ()

    #: Optional operator-facing descriptions, declared beside the owning consumer.
    #: Names must belong to consumer_names.
    consumer_descriptions: tuple[tuple[str, str], ...] = ()

    #: Historical entity destinations, owned independently of any consuming UI.
    entity_links: tuple[EntityLinkSpec, ...] = ()

    #: RADD-1372: where each of this plugin's consumers continues when the plugin
    #: is (re-)enabled. Names must belong to consumer_names; a consumer not
    #: listed resumes from its CURSOR. The plugin manager applies it when the
    #: desired state becomes enabled, so it holds across restarts too.
    consumer_resume: tuple[tuple[str, ConsumerResume], ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", self.name)
        self._reject_unwrapped_contributions()
        for field_name, pairs in (("descriptions", self.consumer_descriptions),
                                  ("consumer_resume", self.consumer_resume)):
            names = [name for name, _value in pairs]
            if len(names) != len(set(names)) or not set(names) <= set(self.consumer_names):
                raise ValueError(
                    f"RaddPlugin({self.name!r}): {field_name} must uniquely name its own consumers"
                )

    def head_consumers(self) -> tuple[str, ...]:
        """The consumers that skip to the stream head on (re-)enable."""
        return tuple(name for name, resume in self.consumer_resume if resume is ConsumerResume.HEAD)

    def _reject_unwrapped_contributions(self) -> None:
        """Refuse a bare value where a tuple is declared: `on_startup=_startup` (RADD-745
        shipped exactly that and the image could not start) or `depends_on="items"` (a str
        iterates as five names). Rejected, not normalised, so one shape stays valid."""
        for name in _TUPLE_FIELDS:
            value = getattr(self, name)
            if isinstance(value, tuple):
                continue
            raise TypeError(
                f"RaddPlugin({self.name!r}): {name}= must be a tuple, got "
                f"{type(value).__name__}. Write {name}=(<value>,) — a single "
                "contribution still needs the trailing comma."
            )


def _tuple_fields() -> tuple[str, ...]:
    """The `tuple[…]` fields, derived from the annotations (string or not, PEP 563 aside) so a
    new contribution is covered the moment it is declared."""
    names = []
    for field in fields(RaddPlugin):
        declared = field.type
        is_tuple = (
            declared.startswith("tuple[")
            if isinstance(declared, str)
            else get_origin(declared) is tuple
        )
        if is_tuple:
            names.append(field.name)
    return tuple(names)


_TUPLE_FIELDS: tuple[str, ...] = _tuple_fields()

