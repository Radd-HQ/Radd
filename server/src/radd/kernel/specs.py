"""Contribution specs — the typed declarations a plugin puts on its manifest.

Frozen dataclasses the loader aggregates into `radd.kernel.registry`. Pure: imports nothing
from `radd.modules.*`."""

from collections.abc import Awaitable, Callable, Mapping
import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class ViewListSpec:
    """A view type drawn by the HOST's list: the plugin supplies ROWS and defaults, never UI
    (selection, bulk actions, columns, paging and the SLQ bar are the list's). Always flat."""

    #: The endpoint serving this type's rows, relative to the API root. It takes the `/items`
    #: paging contract (`q`, `project_id`, `limit`, `offset`) and answers an `ItemRead` list in the
    #: plugin's own ORDER. Empty = `/items` itself. A type with its own rows owns their order, so
    #: manual drag-to-rank is off on it.
    rows_path: str = ""
    #: The column ids a new view of this type starts with (a view's saved `columns` wins);
    #: empty = the list's defaults. Contributed attributes are `<plugin>.<name>`.
    columns: tuple[str, ...] = ()
    #: Re-read the rows this often while the view is open (0 = only when something changes).
    refresh_seconds: int = 0


@dataclass(frozen=True)
class ViewTypeSpec:
    """A saved-view TYPE a plugin contributes (spec 94), drawn by its `view.type` UI slot (keyed
    by `key`) or, with `list_surface`, by the host's list over the plugin's rows."""

    key: str  # the stored view_type value, e.g. "acme.notes"
    label: str  # shown in the create-view Type dropdown
    #: A kebab-case name from the host's icon registry (`web/src/lib/icons.ts`), drawn wherever a
    #: view of this type is listed (header, pins, sidebar). Empty = the generic list icon.
    icon: str = ""
    #: Draw the type on the host's list instead of a `view.type` contribution.
    list_surface: ViewListSpec | None = None
    #: List this type's views in a sidebar section of their own, under this label, each with a
    #: live count badge (`POST /views/counts`) — and out of the ordinary view lists. Empty = an
    #: ordinary view.
    sidebar_section: str = ""


@dataclass(frozen=True)
class WidgetTypeSpec:
    """A dashboard widget TYPE a plugin contributes (spec 94), rendered by the plugin's own
    `dashboard.widget` UI slot (keyed by `key`). Config is a free-form dict the plugin interprets.
    Inverts the hardcoded `WidgetType` enum + its discriminated-union config."""

    key: str  # the stored widget_type value, e.g. "acme.recent-notes"
    label: str  # shown in the add-widget Type dropdown
    #: A PERSONAL widget (RADD-1393): it shows the viewer's own work, so it is offered on My Work
    #: and refused on a shared dashboard, like My Work's own Assigned/Inbox widgets.
    personal: bool = False
    #: My Work's suggested layout: ``await suggest(session, user)`` — True puts this widget on the
    #: person's suggested defaults (approvals: when something awaits their verdict). A personal
    #: widget without it is offered, never suggested. Withdrawn with the plugin like the type.
    suggest: Callable[[Any, Any], Awaitable[bool]] | None = None


@dataclass(frozen=True)
class SlqFieldContext:
    """What a plugin SLQ resolver gets beyond its operands. `me` is a grammar SENTINEL, so
    `is_me` tells `logged_by = me` apart from a person named "me"."""

    current_user_id: uuid.UUID
    #: True when the operand was the bare `me` literal; `value` is then empty
    #: and the resolver should match on `current_user_id`.
    is_me: bool = False


@dataclass(frozen=True)
class SlqFieldSpec:
    """A plugin SLQ field: its own data (`note ~ "x"`) or a relational predicate
    (`logged_by = me`). `item_ids(contains, value, ctx)` returns a `Select` of MATCHING
    work-item ids from the plugin's own table; items wraps it as `id IN (…)` and applies
    negation. Supports `=`, `!=`, `~`."""

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
    #: Spec 123: shown in the audit log by default; False for machine noise
    #: (mail.failed, notification rows, ticks) — still queryable on request.
    audited: bool = True
    entity_type: str = ""  # the entity this event is about (for auto-registered CRUD events)
    #: Entity types this event is ABOUT (RADD-923); the emitter passes ids, the kernel writes
    #: refs. Each needs a registered `EntityRefSpec` or the plugin refuses to LOAD — boot is
    #: the cheapest place to find an unresolvable subject.
    subjects: tuple[str, ...] = ()
    #: JSON Schema for the event's OWN data (subject refs are derived); served by
    #: `GET /automations/samples/events` for types that never fired here.
    payload_schema: dict[str, Any] = field(default_factory=dict)


# --- entity refs (RADD-923: the kernel owns SUBJECTS, plugins own data) -------
@dataclass(frozen=True)
class EntityRefSpec:
    """How to describe one entity type inside an event payload (RADD-923).

    `events.emit` expands `subjects={"item": id}` into `payload["item"] = ref(session, id)`,
    so emitters never hand-build refs. None means the row has gone (a delete resolves its
    subject before the row goes)."""

    entity_type: str
    ref: Callable[..., Any]
    #: Human label for the catalog/dev tooling.
    label: str = ""
    #: RADD-1327: where one of these lives in the SPA, `{id}` substituted — what
    #: a `#` mention of it links to and what the audit log links an entry to.
    #: Empty = no page of its own.
    url: str = ""


@dataclass(frozen=True)
class EntityLinkSpec:
    """Owner-declared destinations for historical entity references.

    Templates are tried in order; missing values fall through to the next one.
    Available values are `id`, `refs.<type>.<field>` and `project.<field>`.
    Substitutions are URI-component encoded. This is navigation metadata only:
    consumers must authorize the underlying data before resolving a destination.
    Unlike EntityRefSpec, it needs no current database row or reference fetch.
    """

    entity_type: str
    templates: tuple[str, ...]

    def __post_init__(self) -> None:
        from .entity_links import validate_templates

        validate_templates(self.entity_type, self.templates)


# --- search + mentions (RADD-1327) --------------------------------------------
@dataclass(frozen=True)
class SearchableSpec:
    """An entity type Cmd-K (and, when `mentionable`, the `#` picker) can find. The OWNER
    answers: `search(session, actor, q, limit)` returns only rows `actor` may read, as
    `{"id", "title", "subtitle"?, "url", "snippet"?}`. A searchable EntitySpec derives one."""

    entity_type: str
    label: str
    search: Callable[..., Any]
    mentionable: bool = False
    #: Lower sorts first in the palette's sections.
    order: int = 100


# --- capabilities (§3 chokepoint 2: /capabilities aggregator) ---
@dataclass(frozen=True)
class CapabilitySpec:
    """What a plugin reports to `/capabilities`. `check()` returns runtime detail that
    overrides `enabled`; a `summary` string in it is the Server status line (RADD-1389)."""

    key: str
    label: str
    category: str = "feature"  # feature | auth | connector | storage | ai | infra
    enabled: bool = True  # static default; `check` overrides at runtime
    check: Callable[[], dict[str, Any]] | None = None


# --- relations (RADD-823: access qualified by who you are to the record) ---
@dataclass(frozen=True)
class RelationActor:
    """What a relation predicate may know about the actor (RADD-823): ids only.
    `team_ids` is the RESOLVED set (direct + group-carried, RADD-830) — never re-derive it."""

    user_id: uuid.UUID
    team_ids: frozenset[uuid.UUID] = frozenset()
    #: Spec 121: the actor is an instance admin — row guards do not apply
    #: (D1: the instance admin bypasses everything; a project manager does not).
    unrestricted: bool = False


@dataclass(frozen=True)
class RowGuardSpec:
    """A per-row ADMISSION every reader passes whatever relation they hold (spec 121): a
    restricted issue admits only the people on it. Composed under every relation set (`@any`
    stops meaning "every row"), so list, count, search and gate agree; `admits` names relation
    KEYS resolved at query time (an unloaded plugin's relation admits nobody)."""

    resource: str
    label: str
    #: FILTERING form of "open to every reader": a boolean expression over the
    #: resource's own table.
    open_where: Callable[[], Any]
    #: GATING form of the same.
    open_holds: Callable[[Any], bool]
    #: Relation keys that admit a reader to a guarded row.
    admits: tuple[str, ...]


@dataclass(frozen=True)
class RelationSpec:
    """What `@<key>` means for one resource's rows (RADD-823).

    `where` (FILTERING) is mandatory: a read restriction must become a WHERE clause or
    lists and counts leak. `holds` (GATING a loaded row) must agree with it —
    tests/test_relation_semantics.py checks the pair. A relation living in another table
    (`@participant`) sets `holds=None` + `expensive=True`: gates then run `where` against
    the row (`authz.relation_holds_row_async`), and sync resolvers treat it as NOT held
    (fail closed)."""

    #: The resource whose rows this qualifies — the atom prefix ("item", "page").
    resource: str
    #: The qualifier: `item.update@own` names the ("item", "own") spec.
    key: str
    #: Inspector/matrix copy: "they reported", "on their team".
    label: str
    #: FILTERING form: (RelationActor) -> a SQLAlchemy boolean expression over
    #: the resource's own table.
    where: Callable[[RelationActor], Any]
    #: GATING form: (RelationActor, row) -> does the relation hold for THIS row?
    #: None = no pure form exists; gate via the where-form (requires expensive).
    holds: Callable[[RelationActor, Any], bool] | None
    #: Required with `holds=None`: a query-gated relation must be declared as one.
    expensive: bool = False
    #: Spec 121: a property of the ROW (`@public`), so holding it ENTITLES the actor to the
    #: project (read by `authz.visible_projects`).
    row_property: bool = False

    def __post_init__(self) -> None:
        if self.holds is None and not self.expensive:
            raise ValueError(
                f"relation {self.resource}@{self.key}: holds=None requires expensive=True "
                "— a query-gated relation must be declared as one"
            )


# --- permissions (§7: RBAC atoms become a registry) ---
@dataclass(frozen=True)
class PermissionSpec:
    """An RBAC atom a plugin defines. Mirrors the shape auth builds from its enum;
    registering one makes it appear in the roles matrix + GET /permissions."""

    key: str
    #: auth.types.PermissionScope value: "project" | "global" | "space".
    scope: str
    description: str = ""
    #: Umbrella atoms that expand to this one (`auth.types.implied_map`).
    implied_by: tuple[str, ...] = ()
    #: The reverse edge: atoms a holder of THIS also holds — including a relation-qualified
    #: form that is not itself a catalog atom (`item.update` → `attachment.delete@own`).
    implies: tuple[str, ...] = ()


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
    """Declarative entity registration → generated model + auto-wired CRUD/events/search/RBAC
    (docs/plugin-platform.md §0.5). `model` is the escape hatch: a code-defined mapped class."""

    key: str  # stable entity type, e.g. "milestone"
    table: str
    label: str
    fields: tuple[EntityFieldSpec, ...] = ()
    model: type | None = None  # escape hatch: a code-defined mapped class
    project_scoped: bool = True
    #: RADD-1327: Cmd-K finds it (a `SearchableSpec` is derived from the table
    #: and the entity's read gate); `mentionable` adds it to the `#` picker.
    searchable: bool = False
    mentionable: bool = False
    plural: str = ""
    #: Where one lives in the SPA (`{id}` substituted) — mentions and audit links.
    url: str = ""


# --- background work (§6: TaskBackend socket) ---
@dataclass(frozen=True)
class TaskSpec:
    """A periodic unit of background work. Consumers register these instead of hand-rolling
    PeriodicLoops; the active TaskBackend runs them."""

    name: str
    run: Callable[[], Awaitable[Any]]
    interval: Callable[[], float] | float | None = None  # tick seconds (None = nothing scheduled)
    gate: Callable[[], bool] | None = None  # e.g. run_workers


# --- automation dataflow (spec 120: a node's outputs are addressable) --------
#: One rule for node names AND output names — both halves of `{{<node>.<output>}}`;
#: lowercase and dot-free (the dot is the separator).
OUTPUT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")


def valid_output_name(name: Any) -> bool:
    return bool(OUTPUT_NAME_RE.match(str(name or "")))


class OutputKind(StrEnum):
    """What a declared output carries. ENUM lets the editor offer the choices and the write
    path refuse a token naming a value the producer never emits; TEXT is anything else."""

    TEXT = "text"
    ENUM = "enum"


@dataclass(frozen=True)
class OutputField:
    """One named value a node PRODUCES, addressable downstream as `{{<node name>.<name>}}`
    (spec 120). Declared, like `ports`, because the editor lists tokens before anything runs."""

    name: str
    label: str = ""
    kind: str = OutputKind.TEXT.value
    #: The values an ENUM output may take. Empty for TEXT.
    choices: tuple[str, ...] = ()
    description: str = ""


# --- notification kinds (RADD-1326) -------------------------------------------
@dataclass(frozen=True)
class NotificationKindSpec:
    """One kind of notification: a preferences-matrix row and, for a CONTRIBUTED kind,
    the `events` that produce it (notify's own kinds leave `events` empty).

    - `personal`: addressed AT the recipients (the `own` column only).
    - `default_channel`: an unset relationship cell — "off" | "inbox" | "email" | "both".
    - `recipients(session, event) -> Iterable[uuid]`; the actor never hears their own action.
    - `render(payload, actor_name) -> {"headline", "link"}`, stored on the row.

    `key` ≤ 30 chars (stored as the notification's type)."""

    key: str
    label: str
    description: str = ""
    personal: bool = True
    default_channel: str = "inbox"
    events: tuple[str, ...] = ()
    recipients: Callable[..., Any] | None = None
    render: Callable[..., Any] | None = None


# --- automation templates (RADD-1316) -----------------------------------------
@dataclass(frozen=True)
class AutomationTemplateSpec:
    """A whole automation offered as a STARTING POINT (RADD-1316): opened as an unsaved,
    DISABLED draft, so nothing runs until someone saves it. `nodes`/`edges` are the stored
    graph shape; a template naming a node type or trigger this instance lacks is not listed."""

    key: str
    name: str
    description: str
    group: str = "Other"
    nodes: tuple[dict[str, Any], ...] = ()
    edges: tuple[dict[str, Any], ...] = ()


# --- template tokens (RADD-1324) ----------------------------------------------
@dataclass(frozen=True)
class TokenProviderSpec:
    """A `{{root.field}}` vocabulary contributed by the entity's owner (RADD-1324).
    `resolve(field, payload)` reads the event payload; None renders the token verbatim."""

    root: str
    #: (field, description) pairs — what the editor's token panel lists.
    tokens: tuple[tuple[str, str], ...]
    resolve: Callable[[str, Mapping[str, Any]], str | None]


# --- trigger kinds (RADD-1323) -------------------------------------------------
@dataclass(frozen=True)
class TriggerKindSpec:
    """A KIND of trigger an automation can start from (RADD-1323).

    * `has_event=False` — a button, a clock, a validation draft: no event to read, so
      nodes with `reads_event` are refused under it; the owning module fires it.
    * `has_event=True` — fired by emitting an event whose type is `key`; the engine asks
      `matches(params, payload)` per automation.

    Plain `EventTypeSpec(trigger=True)` events are not kinds."""

    key: str  # stored as the trigger node's `params.event`
    label: str
    group: str = "Other"
    description: str = ""
    params_schema: dict[str, Any] = field(default_factory=dict)
    default_params: dict[str, Any] = field(default_factory=dict)
    has_event: bool = True
    #: Subject types a MANUAL run or dry run of this kind may be seeded with.
    seeds: tuple[str, ...] = ()
    #: `check(params) -> None`, raising ValueError — the kind's own write-time
    #: validation (a schedule's shape, a validation binding's targets).
    check: Callable[[Mapping[str, Any]], None] | None = None
    #: `matches(params, payload) -> bool` for an event-backed kind: does this
    #: automation's trigger node want THIS firing? None = every firing.
    matches: Callable[[Mapping[str, Any], Mapping[str, Any]], bool] | None = None


def _default_ports_for(_params: Mapping[str, Any]) -> tuple[str, ...]:
    return ("out",)


def _default_outputs_for(_params: Mapping[str, Any]) -> tuple["OutputField", ...]:
    return ()


# --- automation nodes (spec 116 phase 2: the canvas palette is contributed) ---
@dataclass(frozen=True)
class AutomationNodeSpec:
    """A node type an automation graph can hold, contributed by a module.

    Ports belong to the SPEC: fixed `ports`, or `ports_for(params)` when outputs depend
    on configuration (an AI classifier's answers ARE its branches). Static ports are
    DECLARED, not inferred (RADD-1064): `ports_for({})` describes an unconfigured node,
    and the canvas must draw handles before it can ask the server. `ports_at` ranks the two.

    `plan(ctx)` decides and never applies — that split makes dry runs free.
    `params_schema` is JSON Schema; the SPA generates a form when the plugin ships none."""

    key: str  # "filter.slq", "gate.field_changed", "ai.classify"
    kind: str  # AutomationNodeKind value — fixes whether it filters, gates or acts
    label: str
    description: str = ""
    group: str = "Other"  # palette section
    params_schema: dict[str, Any] = field(default_factory=dict)
    #: RADD-1322: extra words the palette search matches (synonyms, the wire key).
    keywords: str = ""
    #: RADD-1322: the params a freshly dropped node starts with — valid enough to
    #: save. Empty = the schema's own defaults.
    default_params: dict[str, Any] = field(default_factory=dict)
    #: Reads the triggering EVENT (its diff, actor, comment), so it is refused under a
    #: trigger with none — it could only answer with a constant (RADD-1322).
    reads_event: bool = False
    #: False for evaluators that execute arbitrary code or have side effects.
    preview_safe: bool = True
    #: RADD-1329: a CHECK that publishes findings (`ctx.publish_findings`) for a
    #: "Block submission" / "Warn submitter" node downstream to relay.
    produces_findings: bool = False
    #: RADD-1329: an END of the graph (the verdict nodes) — no output ports.
    terminal: bool = False
    #: FIXED output ports. Set this OR `ports_for`, never both: declaring it lets a client
    #: draw the handles from the served catalog instead of guessing by kind.
    ports: tuple[str, ...] = ()
    #: Ports for a given params dict, when they genuinely vary. Ignored when `ports` is set.
    ports_for: Callable[[Mapping[str, Any]], tuple[str, ...]] = _default_ports_for
    #: FIXED named values (spec 120), stamped under the node's name; ranked with
    #: `outputs_for` exactly like ports.
    outputs: tuple[OutputField, ...] = ()
    #: Outputs for a given params dict (`ai.generate`'s outputs ARE its typed fields).
    outputs_for: Callable[[Mapping[str, Any]], tuple[OutputField, ...]] = _default_outputs_for
    #: Params used by ports_for/outputs_for. None means all params; a declared
    #: subset avoids shape requests while unrelated prompts or code are edited.
    shape_params: tuple[str, ...] | None = None
    #: False = runs even when nothing reached it (webhook, chat, "nothing matched").
    needs_items: bool = True
    #: How the node reads its packet — a NodeArity value (a string: kernel purity):
    #: "set" runs once, "item" per item (partitioning across ports).
    arity: str = "set"
    #: Arities the author may choose between. Empty = fixed at `arity`, and the
    #: editor shows no control — a toggle with one setting teaches nothing.
    arity_options: tuple[str, ...] = ()
    #: Atom required to USE this node in an automation; "" = any author.
    permission: str = ""
    #: The entity type this node acts on (RADD-923); `ctx.subject_ids` holds ids of it.
    subject: str = "item"
    #: `plan(ctx) -> port name`, used at SET arity: one answer for the packet.
    #: On an ACTION node it returns a `NodePlan`-shaped object (`detail`,
    #: `resolves`) describing what it WOULD do, and writes nothing.
    plan: Callable[..., Any] | None = None
    #: `apply(ctx, plan)` — an ACTION's other half (RADD-923). Runs only when applying,
    #: inside the executor's SAVEPOINT, RunBudget and `events.automated()` scope, so a
    #: contributed action cannot spin the engine or take a branch down.
    apply: Callable[..., Any] | None = None
    #: `check(params)` raising ValueError — write-time validation beyond the generic,
    #: deliberately shallow schema check (required keys, top-level enums, scalar bounds).
    check: Callable[[Mapping[str, Any]], None] | None = None
    #: `check_async(session, params)` — the same, when it needs the database (RADD-1322).
    check_async: Callable[..., Awaitable[None]] | None = None
    #: `plan_items(ctx) -> {item_id: port}` at ITEM arity; optional (the executor
    #: otherwise calls `plan` per single-item packet). Override when work can be batched.
    plan_items: Callable[..., Any] | None = None

    @property
    def dynamic_ports(self) -> bool:
        """Whether this node's ports depend on its params (RADD-1325) — the
        editor asks `POST /automations/nodes/{type}/shape` for those."""
        return not self.terminal and not self.ports and self.ports_for is not _default_ports_for

    @property
    def dynamic_outputs(self) -> bool:
        return not self.outputs and self.outputs_for is not _default_outputs_for

    def ports_at(self, params: Mapping[str, Any]) -> tuple[str, ...]:
        # THE one place static and dynamic ports are ranked; the graph validator relies on it.
        return () if self.terminal else (self.ports or tuple(self.ports_for(params)))

    def outputs_at(self, params: Mapping[str, Any]) -> tuple[OutputField, ...]:
        """Ranked exactly as `ports_at`."""
        return self.outputs or tuple(self.outputs_for(params))


# --- MCP tools (RADD-640: the spec-114 catalog becomes plugin-registerable) ---
@dataclass(frozen=True)
class McpToolSpec:
    """An MCP tool a plugin contributes (RADD-640).

    `visible_catalog` hides it from keys lacking `permission` (and enum-rewrites
    `project_param`, spec 114); with `kernel_enforced` the dispatcher REQUIRES the atom —
    on the `project_param` project when given — before `handler(session, actor, args)`.
    `permission` is an atom KEY; "" = any authenticated principal. Disabling the plugin
    removes catalog entry and dispatch together."""

    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema for the tool's arguments
    handler: Callable[..., Awaitable[Any]]
    permission: str = ""
    project_scoped: bool = False  # visibility: show only where the atom holds (spec 114)
    space_scoped: bool = False
    project_param: str = ""  # input property naming the project; enum-rewritten + enforced
    #: LIVE schema (RADD-889): called with keyword projections (`custom_field_properties`,
    #: `link_types`; accept `**_`) instead of reading `input_schema`.
    input_schema_builder: Callable[..., dict[str, Any]] | None = None
    #: Require `permission` in the dispatcher (default; right for new tools). The migrated
    #: builtins set False: their service seams enforce row rules, and a blanket require
    #: would re-refuse the scoped keys RADD-672 admitted.
    kernel_enforced: bool = True


@dataclass(frozen=True)
class CascadeSpec:
    """Rows that must die with a parent the database cannot cascade from — a POLYMORPHIC
    parent (`entity_type`+`entity_id`) carries no foreign key.

    Registering is a dict entry, not a consumer: `events.cascade` drains the stream once
    for all specs. `sweep(session, parent_id)` runs in the planning transaction
    (committed with the cursor, so a crash can neither lose nor repeat it); its result
    goes to `after_commit`, for effects that must not run inside a transaction (an
    unreachable storage host must leave orphaned bytes, not a stuck consumer)."""

    #: The event that means a parent died, e.g. "item.deleted".
    parent_event: str
    #: What this contribution calls the thing, for logs and tests.
    name: str
    sweep: Callable[..., Awaitable[Any]]
    after_commit: Callable[[Any], Awaitable[None]] | None = None


# --- fact providers (RADD-892): the owning feature declares a fact; a generic consumer
# iterates, instead of holding a list of the features it aggregates.
@dataclass(frozen=True)
class NavFactSpec:
    """One area-visibility fact for `GET /auth/me`'s `nav` (RADD-843). An absent key reads
    as VISIBLE: hiding is presentation, and every area enforces its own authz."""

    key: str  # the key on /auth/me's `nav` object, e.g. "timesheet"
    resolve: Callable[[Any, Any], Awaitable[bool]]  # (session, user) -> is the area worth offering


@dataclass(frozen=True)
class ProjectRelationSpec:
    """Why an actor can see a project WITHOUT a grant on it (RADD-937).

    Qualified permissions (`item.read@own`) must not list every project: each spec
    answers "which projects does this actor have something in?" for one relationship.
    The resolver names no contributor; an unloaded module contributes nothing, which
    narrows visibility — the safe direction."""

    key: str  # "reported" | "assigned" | "team" | "participant" | …
    #: Shown when explaining why a project is visible; keep it a sentence
    #: fragment that completes "visible because …".
    label: str
    #: (session, user) -> the project ids the actor has this relationship with.
    resolve: Callable[[Any, Any], Awaitable[set[Any]]]


@dataclass(frozen=True)
class GrantScopeSpec:
    """A kind of thing a role grant binds to (project, wiki space). `key` names the grant
    row's `<key>_id` column, so a new kind still needs a migration; this inverts only the
    KNOWLEDGE auth lacks (labels, existence, reach). `reach` is optional: only a kind with
    its own ACLs (spaces) answers it."""

    key: str
    labels: Callable[[Any, Any], Awaitable[dict]]  # (session, ids) -> {id: display name}
    exists: Callable[[Any, Any], Awaitable[bool]]  # (session, id) -> is this a real scope
    reach: Callable[[Any, Any], Awaitable[tuple[int, int]]] | None = None  # -> (readable, total)


@dataclass(frozen=True)
class ProjectPurgeSpec:
    """Tables to DELETE from when a project dies, because their `project_id` FK has no
    `ON DELETE CASCADE`. Table names, not a callback, so coverage is checkable
    (tests/test_project_purge.py); a plain DELETE, because teardown must not re-run authz
    or emit events. `tables` go in order; `order` sequences specs (low first)."""

    name: str
    tables: tuple[str, ...]
    order: int = 50


# --- page extensions (RADD-709: live blocks embedded in a page's markdown) ---
@dataclass(frozen=True)
class PageExtensionSpec:
    """An extension a page embeds as a fenced block (```` ```radd:<name> ````).

    Declaration only — rendering is client-side, by name. The registry feeds the editor's
    insert menu (`GET /pages/extensions`), so a plugin's toggle adds/removes its entry; a
    stale block renders an "unknown extension" card. `params_schema` is advisory JSON
    Schema: hand-typed markdown must always render."""

    name: str  # the fence suffix: `toc` for ```radd:toc
    label: str  # insert-menu title
    description: str = ""  # one line, insert-menu subtitle
    params_schema: dict[str, Any] = field(default_factory=dict)
    icon: str = ""  # lucide icon name, for the insert menu


# --- sockets (§4a: typed plugin-to-plugin integration points) ---
@dataclass(frozen=True)
class IntegrationSpec:
    """A plugin providing a named socket (`kernel.sockets.Socket`)."""

    socket: str
    name: str
    impl: Any = None  # provider instance/factory


# --- settings (§ settings: keys + admin sections owned per plugin, RADD-891) ---
@dataclass(frozen=True)
class SettingSpec:
    """A scalar cascade setting a plugin contributes (RADD-891). `settings` owns the
    cascade (project → instance → env) and reads this catalog; `type`/`scopes` are plain
    strings because kernel purity forbids importing `settings.types`."""

    key: str
    type: str  # "string" | "int" | "bool" (settings.types.SettingType values)
    scopes: tuple[str, ...]  # cascade levels this key may be SET at: "instance" | "project"
    label: str = ""
    description: str = ""
    # `config.Settings` attribute holding the env default when it differs from `key`.
    config_attr: str = ""
    # Enumerated STRING settings (spec 107): the only accepted values — a write
    # outside the set 409s, and the generic settings editor renders a select.
    choices: tuple[str, ...] | None = None
    # Sealed at rest and never read back over the settings API (RADD-1424, RADD-1454):
    # the list reports only whether one is set, and the editor takes a replacement.
    secret: bool = False
    # RADD-1368: a STRING setting that holds prose (a mail body) — the editor
    # renders a textarea instead of a single-line input. Presentation only.
    multiline: bool = False
    # Settings surface this key belongs on (RADD-930); "" = the scope's General page, which
    # renders the REMAINDER, so a departed or misspelt section never hides a setting.
    section: str = ""
    # Scopes at which the owner renders this on a page of its OWN (General skips it there).
    page_scopes: tuple[str, ...] = ()
    # `guard(session, value, actor_id)` may veto a write (409/403) after coercion — policy
    # is the owner's (e.g. `require_mfa` refuses to lock out the admin flipping it).
    guard: Callable[[Any, Any, "uuid.UUID | None"], Awaitable[None]] | None = None

    @property
    def default(self) -> Any:
        """The env/config default (the kernel may read `radd.config`)."""
        from radd.config import settings as _config

        return getattr(_config, self.config_attr or self.key)


# --- frontend (§8: UI manifest) ---
class NavSection(StrEnum):
    """Where a contributed nav entry is listed, and so which page slot draws it."""

    #: The left sidebar; `path` is an absolute in-app path drawn by a `route.page` contribution.
    MAIN = "main"
    #: Settings; `path` is under `/settings` and drawn by a `settings.page` contribution.
    SETTINGS = "settings"
    #: A project's settings (RADD-1396). `path` is the page's SEGMENT under
    #: `/p/<KEY>/settings/`, drawn by a `project.settings.page` contribution matched on it, and
    #: `requires` atoms are checked IN that project.
    PROJECT_SETTINGS = "project_settings"


@dataclass(frozen=True)
class NavItemSpec:
    key: str
    label: str
    path: str
    icon: str = ""
    section: str = NavSection.MAIN  # a NavSection value
    requires: tuple[str, ...] = ()  # permission atoms gating visibility
    order: int = 100
    capability: str = ""  # hide unless this capability is enabled
    group: str = ""  # optional settings navigation group label
    requires_admin: bool = False
    #: Each atom must hold in at least one project; navigation only, never authorization.
    requires_any_project: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginUiManifest:
    """Nav/routes/pages a plugin contributes to the SPA (docs/plugin-platform.md §8)."""

    nav: tuple[NavItemSpec, ...] = ()
    # URL of the plugin's built ESM remote (spec 94); its `activate()` registers UI slots.
    # Builtin remotes are served same-origin under /plugins/<name>/.
    remote: str = ""
    # Minimum @radd/plugin-sdk version the remote needs; the host refuses another major or a
    # newer minor/patch.
    ui_api_version: str = ""
    # The entity types the remote's UI serves LIVE documents for (its `definePlugin({ liveDocuments })`
    # sources, e.g. "page"). Declared here so the host can hold a document's own editor back while the
    # remote is still loading — a session that lands after typing began would replace the draft.
    live_documents: tuple[str, ...] = ()
