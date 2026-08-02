"""Contribution specs — the typed declarations a plugin puts on its manifest.

Each spec is a frozen dataclass the loader aggregates into a kernel registry
(`radd.kernel.registry`). The kernel iterates the registries blind — no consumer
names a plugin. These are the vocabulary of the plugin platform (docs/plugin-platform.md §4).

Kept deliberately pure: this module imports nothing from `radd.modules.*`, so the
kernel never depends on a plugin. Specs carry data + light callables only.
"""

from collections.abc import Awaitable, Callable
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ViewTypeSpec:
    """A saved-view TYPE a plugin contributes (spec 94) — like board/list/roadmap, but rendered by
    the plugin's own `view.type` UI slot (keyed by `key`). The view still stores its SLQ `query` +
    config; the plugin just owns the presentation. Inverts the hardcoded `ViewType` enum."""

    key: str  # the stored view_type value, e.g. "acme.notes"
    label: str  # shown in the create-view Type dropdown


@dataclass(frozen=True)
class WidgetTypeSpec:
    """A dashboard widget TYPE a plugin contributes (spec 94), rendered by the plugin's own
    `dashboard.widget` UI slot (keyed by `key`). Config is a free-form dict the plugin interprets.
    Inverts the hardcoded `WidgetType` enum + its discriminated-union config."""

    key: str  # the stored widget_type value, e.g. "acme.recent-notes"
    label: str  # shown in the add-widget Type dropdown


@dataclass(frozen=True)
class SlqFieldContext:
    """What a plugin SLQ resolver needs from the query beyond its own operands.

    `me` is a grammar SENTINEL, not a string — the parser marks it unquoted and
    the builtin people fields branch on it rather than text-matching. Plugin
    resolvers get the same distinction as a typed flag, so `logged_by = me` and
    a person literally named "me" cannot be confused.

    Passing a context object rather than the id itself means the next thing a
    resolver needs (a project scope, a timezone) is an added attribute, not
    another signature break."""

    current_user_id: uuid.UUID
    #: True when the operand was the bare `me` literal; `value` is then empty
    #: and the resolver should match on `current_user_id`.
    is_me: bool = False


@dataclass(frozen=True)
class SlqFieldSpec:
    """A custom SLQ query field a plugin contributes — the SLQ engine's inversion of its hardcoded
    field set. Two uses, same mechanism: a plugin's OWN data (`note ~ "foo"`), and RELATIONAL
    predicates over a module's child rows (`logged_by = me`, `commented_by = "alice@corp.example"` —
    find issues by who logged time on them or commented on them).

    `item_ids` returns a SQLAlchemy `Select` of the work-item ids that MATCH (positive sense); the
    items query engine wraps it as `work_item.id IN (…)` and applies negation. The resolver builds
    the subquery from the plugin's OWN table only (joining the `auth.User` spine is fine), so the
    plugin stays decoupled from the items model and items never learns about worklogs or comments.
    Supports `=`, `!=`, and `~` (contains)."""

    name: str  # the SLQ field keyword, e.g. "note"
    label: str  # human label (autocomplete / errors)
    # (contains, value, ctx) -> Select[work_item_id]. `contains` is True for `~`, False for `=`.
    item_ids: Callable[[bool, str, SlqFieldContext], Any]


# --- events (§3 chokepoint 1: automations derives its trigger list from here) ---
@dataclass(frozen=True)
class EventTypeSpec:
    """A registered event type. `trigger=True` makes it an automation trigger with
    the builder metadata the UI needs — the inversion of the hardcoded catalog."""

    event_type: str
    label: str
    group: str = "Other"
    item_scoped: bool = False  # a target item resolves → SLQ + item actions apply
    has_changes: bool = False  # payload carries a field diff (old/new subjects work)
    trigger: bool = True  # appears in the automation trigger catalog
    entity_type: str = ""  # the entity this event is about (for auto-registered CRUD events)


# --- capabilities (§3 chokepoint 2: /capabilities aggregator) ---
@dataclass(frozen=True)
class CapabilitySpec:
    """What a plugin reports to `/capabilities` — a status/flag descriptor. `check`
    is an optional callable returning extra runtime detail (e.g. whether SSO is
    configured). Replaces the inlined provider `enabled()` logic in /instance/status."""

    key: str
    label: str
    category: str = "feature"  # feature | auth | connector | storage | ai | infra
    enabled: bool = True  # static default; `check` overrides at runtime
    check: Callable[[], dict[str, Any]] | None = None


# --- permissions (§7: RBAC atoms become a registry) ---
@dataclass(frozen=True)
class PermissionSpec:
    """An RBAC atom a plugin defines. Mirrors the shape auth builds from its enum;
    registering one makes it appear in the roles matrix + GET /permissions."""

    key: str
    scope: str  # "project" | "global" | "instance"
    description: str = ""
    implied_by: tuple[str, ...] = ()  # umbrella atoms that expand to this one


@dataclass(frozen=True)
class CrudResourceSpec:
    """A resource exposing granular create/update/delete atoms + its umbrella (spec 50).
    Kernel mirror of auth.types.ResourceSpec so plugins register without importing auth."""

    key: str
    scope: str
    label: str
    manage: str  # the coarse verb whose holders get all of this resource's atoms
    actions: tuple[str, ...] = ("create", "update", "delete")


# --- entities (§0.5 mediation / auto-wiring) ---
@dataclass(frozen=True)
class EntityFieldSpec:
    name: str
    type: str  # "str" | "text" | "int" | "float" | "bool" | "uuid" | "datetime" | "json"
    nullable: bool = True
    default: Any = None
    index: bool = False
    unique: bool = False
    fk: str = ""  # "work_items.id" — cross-plugin FK (kernel-owned)


@dataclass(frozen=True)
class EntitySpec:
    """Declarative entity registration → generated model + auto-wired CRUD/events/
    activity/search/RBAC (docs/plugin-platform.md §0.5). `model` is the code
    escape-hatch: a plugin-defined SQLAlchemy model registered through the kernel."""

    key: str  # stable entity type, e.g. "milestone"
    table: str
    label: str
    fields: tuple[EntityFieldSpec, ...] = ()
    model: type | None = None  # escape hatch: a code-defined mapped class
    project_scoped: bool = True
    searchable: bool = False
    mentionable: bool = False
    activity: bool = True
    plural: str = ""


# --- background work (§6: TaskBackend socket) ---
@dataclass(frozen=True)
class TaskSpec:
    """A unit of background work: a periodic tick or an enqueueable job. Consumers
    register these instead of hand-rolling PeriodicLoops; the active TaskBackend runs them."""

    name: str
    run: Callable[[], Awaitable[Any]]
    interval: Callable[[], float] | float | None = None  # periodic tick seconds (None = enqueue-only)
    gate: Callable[[], bool] | None = None  # e.g. run_workers


@dataclass(frozen=True)
class ConsumerSpec:
    """An offset-tracked event-stream consumer (kept lightweight; today's consumers
    stay hand-rolled loops — this records them for the manifest/capabilities view)."""

    name: str
    description: str = ""


# --- sockets (§4a: typed plugin-to-plugin integration points) ---
@dataclass(frozen=True)
class IntegrationSpec:
    """A plugin providing (or consuming) a named socket: StorageBackend, Notifier,
    Connector, AIProvider, VcsProvider, TaskBackend, AttachmentFilter."""

    socket: str
    name: str
    impl: Any = None  # provider instance/factory
    consumes: bool = False


# --- settings (§ settings: keys + admin sections owned per plugin) ---
@dataclass(frozen=True)
class SettingSectionSpec:
    key: str
    label: str
    scope: str = "instance"  # instance | project


# --- frontend (§8: UI manifest) ---
@dataclass(frozen=True)
class NavItemSpec:
    key: str
    label: str
    path: str
    icon: str = ""
    section: str = "main"  # main | settings
    requires: tuple[str, ...] = ()  # permission atoms gating visibility
    order: int = 100
    capability: str = ""  # hide unless this capability is enabled


@dataclass(frozen=True)
class PluginUiManifest:
    """Nav/routes/pages a plugin contributes to the SPA (docs/plugin-platform.md §8)."""

    nav: tuple[NavItemSpec, ...] = ()
    # Module-federation remote (spec 94 / §8b-A): the URL of the plugin's built ESM bundle, which the
    # host imports at runtime and whose `activate()` registers its UI slots. Builtin remotes are
    # served same-origin under /plugins/<name>/; external plugins serve their own.
    remote: str = ""
    # The @radd/plugin-sdk major the remote was built against; the host loader refuses an
    # incompatible major (§9). Only meaningful when `remote` is set.
    ui_api_version: str = ""
