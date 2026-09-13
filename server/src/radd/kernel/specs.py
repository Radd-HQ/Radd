"""Contribution specs — the typed declarations a plugin puts on its manifest.

Each spec is a frozen dataclass the loader aggregates into a kernel registry
(`radd.kernel.registry`). The kernel iterates the registries blind — no consumer
names a plugin. These are the vocabulary of the plugin platform (docs/plugin-platform.md §4).

Kept deliberately pure: this module imports nothing from `radd.modules.*`, so the
kernel never depends on a plugin. Specs carry data + light callables only.
"""

from collections.abc import Awaitable, Callable, Mapping
import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
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
    #: Entity types this event is ABOUT (RADD-923) — `("item",)`, `("item",
    #: "release")`, `("milestone",)`. Each must have a registered `EntityRefSpec`
    #: or the plugin refuses to LOAD: an event promising a subject nothing can
    #: resolve is an automation that silently does nothing at 3am, and boot is
    #: the cheapest place to find out.
    #:
    #: The emitter passes these as IDS and the kernel writes the refs, so a
    #: declared subject is a promise the emitter cannot forget to keep.
    subjects: tuple[str, ...] = ()
    #: JSON Schema for the event's OWN data — not the subject refs, which the
    #: kernel writes and therefore already knows the shape of. Deriving beats
    #: declaring: a schema that repeats what the kernel generated is a second
    #: copy that drifts. This covers only the remainder (`{"environment": …}`).
    #:
    #: Served by `GET /automations/samples/events`, which otherwise has nothing
    #: to show for an event type that has never fired on this instance.
    payload_schema: dict[str, Any] = field(default_factory=dict)


# --- entity refs (RADD-923: the kernel owns SUBJECTS, plugins own data) -------
@dataclass(frozen=True)
class EntityRefSpec:
    """How to describe one entity type inside an event payload.

    Registered once by the module that owns the entity; used by `events.emit` to
    expand `subjects={"item": id}` into `payload["item"] = {id, key, title, …}`.

    **Why the kernel resolves rather than the emitter building.** RADD-922 found
    fourteen hand-built shapes for the same idea, fixed them, and left an AST
    test to keep them fixed — a test that is only necessary because the shape is
    still hand-built. Handing the kernel an ID deletes the failure mode instead
    of policing it: you cannot forget to build a ref you never build, and eleven
    emitters stop needing `depends_on items` to describe an item.

    `ref(session, entity_id) -> dict | None`. None means the row has gone, which
    is a real answer — a delete event resolves its subject BEFORE the row goes,
    and anything racing it legitimately finds nothing.
    """

    entity_type: str
    ref: Callable[..., Any]
    #: Human label for the catalog/dev tooling.
    label: str = ""


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


# --- relations (RADD-823: access qualified by who you are to the record) ---
@dataclass(frozen=True)
class RelationActor:
    """What a relation predicate may know about the acting user (RADD-823).

    Deliberately tiny: relations are structural facts about columns
    (`reporter_id = :me`, `team_id IN :my_teams`), so the actor is ids only —
    never the User row, never a session. `team_ids` is the RESOLVED set (the
    RADD-830 subject graph: direct + group-carried, memoised per request);
    a relation predicate must not re-derive it."""

    user_id: uuid.UUID
    team_ids: frozenset[uuid.UUID] = frozenset()
    #: Spec 121: the actor is an instance admin — row guards do not apply
    #: (D1: the instance admin bypasses everything; a project manager does not).
    unrestricted: bool = False


@dataclass(frozen=True)
class RowGuardSpec:
    """A per-row ADMISSION every reader of a resource passes, whatever relation
    they hold (spec 121 §3): a restricted issue admits only the people on it.

    A relation says who the actor is to a row; a guard says which rows are
    open to everyone who may read the resource at all, and which relations
    ADMIT a reader to the rest. The resolvers compose it under every relation
    set — `@any` stops meaning "every row" the moment a guard is registered —
    so a list, a count, a search and a gate agree by construction. `admits`
    names relation KEYS resolved through the registry at query time, so an
    unloaded plugin's relation simply does not admit.
    """

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
    """One relation a resource contributes: what `@own` / `@team` MEAN for its
    rows (RADD-823). Only the owning module knows — the kernel carries the
    declaration and the resolvers compose it.

    The FILTERING form is mandatory: a read restriction must become a WHERE
    clause or every list, count and aggregate leaks. The GATING form (`holds`)
    is asked about a row already loaded; a column relation supplies it as a
    pure predicate, and the pair must agree — the contract test in
    tests/test_relation_semantics.py asserts it on a fixture, because a pair
    that DISAGREES is a silent leak. A relation whose membership lives in
    ANOTHER table (`@participant`, RADD-844) has no pure row form: it sets
    `holds=None` + `expensive=True`, and gates answer it by running `where`
    against that one row (`authz.relation_holds_row_async`). Sync resolvers
    treat a None-holds relation as NOT held — failing closed, never wide.
    """

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
    #: A relation needing a join ("issues shared with me") is expressible but
    #: marked, so hot paths can decline it — never silently slow.
    expensive: bool = False
    #: Spec 121: the relation is a property of the ROW, not of who the actor
    #: is (`@public` = the item's own visibility). Holding `item.read@public`
    #: on a project therefore ENTITLES the actor to the project (it appears in
    #: their rail) rather than merely relating them to rows they happen to be
    #: on — `authz.visible_projects` reads this flag.
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
    #: One of auth.types.PermissionScope: "project" | "global" | "space".
    #: RADD-814 retired "instance" (zero atoms, no resolution branch); RADD-791
    #: added "space" — kept in step by the scope contract test (RADD-818).
    scope: str
    description: str = ""
    #: Umbrella atoms that expand to this one. RADD-890 wired it into
    #: `auth.types.implied_map()` — it was declared in spec 93 and read by
    #: nothing, so a plugin atom could not ride an umbrella at all.
    implied_by: tuple[str, ...] = ()
    #: The reverse edge: atoms a holder of THIS one also holds. Needed because
    #: `implied_by` can only name the umbrella, and an implication may confer a
    #: RELATION-QUALIFIED form that is not itself a catalog atom — `item.update`
    #: confers `attachment.delete@own` (RADD-790/816), which has no PermissionSpec
    #: of its own and must not appear in the catalog.
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


# --- automation dataflow (spec 120: a node's outputs are addressable) --------
#: What a node's OUTPUT may be called, and equally what may NAME a node — the two
#: halves of `{{<node>.<output>}}` are read as one identifier, so one rule covers
#: both rather than two regexes that eventually disagree about an underscore.
#: Lowercase and dot-free: the dot is the separator, and a name carrying one
#: could not be told from a node-plus-field pair.
OUTPUT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")


def valid_output_name(name: Any) -> bool:
    return bool(OUTPUT_NAME_RE.match(str(name or "")))


class OutputKind(StrEnum):
    """What a declared output carries.

    The kernel's OWN vocabulary rather than a module's — `OutputField` lives
    here, so what its `kind` may say lives here too. That is the difference from
    `AutomationNodeSpec.arity`, which is a plain string precisely because
    `NodeArity` belongs to `automations`.

    ENUM is not decoration: a producer that declares its choices lets the graph
    editor offer them and lets the write path refuse a token naming a value the
    producer can never emit. TEXT is anything else, stringified.
    """

    TEXT = "text"
    ENUM = "enum"


@dataclass(frozen=True)
class OutputField:
    """One named value a node PRODUCES, addressable downstream as
    `{{<node name>.<name>}}` (spec 120).

    Declared, not inferred, for the reason `ports` is declared (RADD-1064): the
    graph editor has to list what a downstream token may say BEFORE anything has
    run, and a value discovered only at run time can only be offered after it is
    too late to reference it.
    """

    name: str
    label: str = ""
    kind: str = OutputKind.TEXT.value
    #: The values an ENUM output may take. Empty for TEXT.
    choices: tuple[str, ...] = ()
    description: str = ""


# --- automation nodes (spec 116 phase 2: the canvas palette is contributed) ---
@dataclass(frozen=True)
class AutomationNodeSpec:
    """A node type an automation graph can hold, contributed by a module.

    Before this, node behaviour was a closed set of `if kind is …` branches in
    the executor and a hardcoded palette in the SPA — so the AI module could not
    offer a classifier node, and every new condition meant editing `automations`.

    Two things make ports part of the SPEC rather than of the KIND:

    * A condition node is one named test ("field changed", "changed by"), and
      each names its own outputs.
    * `ports_for(params)` lets a node's outputs depend on its CONFIGURATION — an
      AI classifier with four user-defined answers has four outputs. A fixed
      tuple ALONE could not express that, and the graph validator has to know the
      real set or it cannot reject an edge naming a port that will not exist.

    **Static ports are DECLARED, not inferred (RADD-1064).** Most contributed
    nodes' outputs do not depend on their params at all, and `ports_for({})` is
    not a way to find that out: for a dynamic node it answers about a node that
    has not been configured yet. So a node whose ports are fixed says so in
    `ports`, and everything that has to draw a node BEFORE it can ask the server
    about a particular params dict — the canvas, above all — has an answer it can
    trust. `ai.validate` drew TRUE/FALSE handles for a whole release because the
    SPA had nowhere to read `("pass", "fail", "unavailable")` from and fell back
    to the KIND's table; every edge wired from those handles named a port the
    engine never emits. Resolution is `ports_at(params)`, in one place.

    `plan(ctx) -> NodeOutcome` decides what the node does; it never applies. That
    split is what gives dry-run for free and is enforced by the executor calling
    planners only.

    `params_schema` is JSON Schema. The SPA generates a form from it when the
    plugin ships no component of its own, which is the same deal PageExtensionSpec
    offers — a plugin gets a usable editor without writing React.
    """

    key: str  # "filter.slq", "gate.field_changed", "ai.classify"
    kind: str  # AutomationNodeKind value — fixes whether it filters, gates or acts
    label: str
    description: str = ""
    group: str = "Other"  # palette section
    params_schema: dict[str, Any] = field(default_factory=dict)
    #: FIXED outputs, for a node whose ports do not depend on its params. Set
    #: this OR `ports_for`, never both — declaring it is what lets a client draw
    #: the node's handles from the served catalog instead of guessing by kind.
    ports: tuple[str, ...] = ()
    #: Outputs for a given params dict, when they genuinely vary (an AI
    #: classifier's answers ARE its branches). Ignored when `ports` is set.
    ports_for: Callable[[Mapping[str, Any]], tuple[str, ...]] = lambda _params: ("out",)
    #: FIXED named values this node produces (spec 120), stamped into the
    #: packet's variable bag under the node's name. Same static-or-dynamic pair
    #: as ports, ranked the same way in `outputs_at` — and for the same reason:
    #: a client listing the tokens a downstream node may use has to know the set
    #: before anything has run.
    outputs: tuple[OutputField, ...] = ()
    #: Outputs for a given params dict, when they vary. `ai.generate`'s outputs
    #: ARE its params — the fields someone typed — which no static tuple can say.
    outputs_for: Callable[[Mapping[str, Any]], tuple[OutputField, ...]] = lambda _params: ()
    #: False = runs even when nothing reached it (webhook, chat, "nothing matched").
    needs_items: bool = True
    #: How the node reads its packet — a `NodeArity` value, "set" or "item"
    #: (RADD-918). SET runs once over the whole set; ITEM runs per item, which
    #: for a routing node means PARTITIONING the set across its ports rather
    #: than sending all of it down one. Strings rather than the enum because the
    #: kernel may not import a module's vocabulary.
    arity: str = "set"
    #: Arities the author may choose between. Empty = fixed at `arity`, and the
    #: editor shows no control — a toggle with one setting teaches nothing.
    arity_options: tuple[str, ...] = ()
    #: Atom required to USE this node in an automation; "" = any author.
    permission: str = ""
    #: Which SUBJECT this node acts on (RADD-923) — the entity type it wants out
    #: of the packet. "item" for everything built in; a plugin's own entity for
    #: an action on its own rows. The executor hands `ctx.subject_ids` the ids of
    #: exactly this type, so a node that acts on milestones never has to know
    #: how an item-shaped packet is put together.
    subject: str = "item"
    #: `plan(ctx) -> port name`, used at SET arity: one answer for the packet.
    #: On an ACTION node it returns a `NodePlan`-shaped object (`detail`,
    #: `resolves`) describing what it WOULD do, and writes nothing.
    plan: Callable[..., Any] | None = None
    #: `apply(ctx, plan)` — an ACTION node's other half (RADD-923).
    #:
    #: The split is the safety property, not a style preference. `plan` runs on
    #: every walk including a dry run, so the report is free and identical to the
    #: real thing; `apply` runs only when applying, inside the executor's
    #: SAVEPOINT, inside its `RunBudget`, and inside the `events.automated()`
    #: scope. A contributed action therefore cannot spin the engine, cannot
    #: escape the budget, and cannot take a branch down when it raises.
    apply: Callable[..., Any] | None = None
    #: `check(params) -> None`, raising `ValueError` — the node's own write-time
    #: validation, for what its JSON Schema cannot say and the generic checker
    #: must not guess (spec 120).
    #:
    #: The generic checker is deliberately shallow (required keys, top-level
    #: enums, and the scalar bounds a generated form already respects), because
    #: a full JSON Schema validator there would be a second, stricter opinion
    #: than the form that offered the value. Anything DEEPER belongs to the node:
    #: `ai.generate` caps its field list, refuses a field name that could never
    #: appear in a token, and caps each field's choices — none of which a
    #: shallow reader can see, and all of which are silently truncated at run
    #: time if nobody says so on write.
    check: Callable[[Mapping[str, Any]], None] | None = None
    #: `plan_items(ctx) -> {item_id: port name}`, used at ITEM arity, where the
    #: node PARTITIONS its input across its ports. Optional: without it the
    #: executor falls back to calling `plan` once per single-item packet, which
    #: is correct for any node and is the whole feature for a cheap one. A node
    #: whose per-item work is expensive overrides it — only the node knows
    #: whether its calls can be batched or run concurrently, so that decision
    #: does not belong in the executor.
    plan_items: Callable[..., Any] | None = None

    def ports_at(self, params: Mapping[str, Any]) -> tuple[str, ...]:
        """This node's outputs for these params — the ONE place the two
        declarations are ranked.

        A second copy of "static wins over dynamic" anywhere would eventually
        disagree with this one, and the graph validator cannot survive that: it
        rejects edges against a port set it has to believe.
        """
        return self.ports or tuple(self.ports_for(params))

    def outputs_at(self, params: Mapping[str, Any]) -> tuple[OutputField, ...]:
        """The named values this node produces for these params — ranked exactly
        as `ports_at` ranks ports, because the two answer the same shape of
        question and a second precedence would drift from this one."""
        return self.outputs or tuple(self.outputs_for(params))


# --- MCP tools (RADD-640: the spec-114 catalog becomes plugin-registerable) ---
@dataclass(frozen=True)
class McpToolSpec:
    """An MCP tool a plugin contributes. The last hardcoded contribution type:
    every other kind was plugin-registerable since spec 93, while the MCP catalog
    was a closed enum — a plugin could not expose a tool at all, and one that
    somehow did would have bypassed the spec-114 caller filter.

    A registered tool inherits BOTH halves with no extra code: `visible_catalog`
    hides it from keys lacking `permission` (and enum-rewrites `project_param`,
    spec 114), and the MCP dispatcher REQUIRES the atom before the handler runs —
    so a plugin cannot accidentally expose an unfiltered tool. Disabling the
    plugin unregisters it (the spec-94 unmount path): it leaves the catalog and
    stops dispatching in the same breath.

    `handler(session, actor, args) -> jsonable` — the tool result, serialized by
    the MCP router. `permission` is an RBAC atom KEY (a plugin's registered atom
    or a builtin value like "item.read"; kernel purity forbids importing the auth
    enum here); "" means any authenticated principal. When `project_param` names
    an input property carrying a project KEY, enforcement resolves it and
    requires the atom on THAT project."""

    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema for the tool's arguments
    handler: Callable[..., Awaitable[Any]]
    permission: str = ""
    project_scoped: bool = False  # visibility: show only where the atom holds (spec 114)
    project_param: str = ""  # input property naming the project; enum-rewritten + enforced
    #: LIVE schema (RADD-889): when set, the catalog composer calls it with
    #: keyword projections — today `custom_field_properties` (the field
    #: registry's OpenAPI properties) and `link_types` (the instance's link-type
    #: keys), the parameters `build_catalog` always took — instead of reading
    #: `input_schema`. Builders accept ``**_`` so a new projection never breaks
    #: an old one; `input_schema` stays as the same shape with the projections
    #: empty, for pure consumers and as documentation.
    input_schema_builder: Callable[..., dict[str, Any]] | None = None
    #: When True (the default, and right for every NEW tool) the dispatcher
    #: requires `permission` — on the `project_param` project when given —
    #: before the handler runs, so a plugin cannot expose an unfiltered tool.
    #: The migrated spec-45/114 builtins set False: their handlers already carry
    #: enforcement at the service seam (row-level rules, require-ANYWHERE gates),
    #: and a blanket global `require` on top would re-refuse the scoped keys
    #: RADD-672 admitted. `permission` still drives the spec-114 catalog filter.
    kernel_enforced: bool = True


@dataclass(frozen=True)
class CascadeSpec:
    """Rows that must die with a parent the database cannot cascade from.

    Three registries had independently grown the same hole. `attachments` and
    `comments` key their rows to a POLYMORPHIC parent (`entity_type` +
    `entity_id`), which cannot carry a foreign key, so `ON DELETE CASCADE` is
    unavailable. `access_grants` keys to `resource_type` + `resource_id` for the
    same reason. Each answered it differently — two head-seeded consumers and, in
    access's case, four call sites that each have to remember.

    One registry and ONE consumer instead:

      - **performant** — a cascade is not worth its own cursor and its own poll
        of the events table; there are already 18 such loops. Registering here
        costs a dict entry, not a background task.
      - **extensible** — a plugin registers a cascade and gets cleanup, with no
        edit to a module it does not own. That was the point of the polymorphic
        parent, and it was exactly what the hardcoded maps took away.

    `sweep(session, parent_id)` runs in the consumer's PLANNING transaction,
    which is committed with the cursor — so a crash between the two cannot lose
    the work or repeat it. Whatever it returns is handed to `after_commit`, for
    the effects that must not run inside a transaction: attachments removes bytes
    from a storage host there, because an unreachable host must leave orphaned
    bytes rather than a stuck consumer.
    """

    #: The event that means a parent died, e.g. "item.deleted".
    parent_event: str
    #: What this contribution calls the thing, for logs and tests.
    name: str
    sweep: Callable[..., Awaitable[Any]]
    after_commit: Callable[[Any], Awaitable[None]] | None = None


# --- fact providers (RADD-892: the aggregation inversion) ---
#
# Three registries, one shape: the feature that OWNS a fact declares it, and a
# generic consumer iterates. Each replaces a consumer that had grown a hardcoded
# list of the features it aggregated — auth reaching into timelogging/forms for
# nav visibility and into pages for space names, jiraimport naming seven other
# modules' tables by string — which inverts the load order those consumers are
# supposed to sit above.
@dataclass(frozen=True)
class NavFactSpec:
    """One area-visibility answer the client cannot derive from lists it already
    loads (RADD-843).

    The consumer (`GET /auth/me`) does not know which facts exist; it serves
    whatever is registered, keyed by `key`. A module that is not loaded
    contributes no fact and the key is simply absent, which the SPA reads as
    VISIBLE — hiding is presentation, every area still enforces its own authz on
    direct navigation, and failing open here costs a link, never a leak.
    """

    key: str  # the key on /auth/me's `nav` object, e.g. "timesheet"
    resolve: Callable[[Any, Any], Awaitable[bool]]  # (session, user) -> is the area worth offering


@dataclass(frozen=True)
class ProjectRelationSpec:
    """Why an actor can see a project WITHOUT having been granted it (RADD-937).

    Qualified permissions (`item.read@own`, `@participant`) say "you may read
    your own rows anywhere", which the project list read as "every project is
    yours" — an account with no grants at all was listed against all 97. The
    fix is not to drop the qualifier, which is what people's own tickets rest
    on, but to require that the relationship is REAL: you see a project you
    actually have something in.

    Each spec answers, for one kind of relationship, "which projects does this
    actor have something in?". `items` contributes reported/assigned/team-owned;
    `participants` contributes participation. The resolver reads whatever is
    registered and names none of them — `auth` must not grow an import of
    `items` to answer a question about items, and the next module that creates a
    relationship (worklogs: "I logged time there") contributes without editing
    it. The RADD-892 inversion, one registry over.

    A module that is not loaded contributes nothing, which narrows visibility
    rather than widening it — the safe direction for a fail case.
    """

    key: str  # "reported" | "assigned" | "team" | "participant" | …
    #: Shown when explaining why a project is visible; keep it a sentence
    #: fragment that completes "visible because …".
    label: str
    #: (session, user) -> the project ids the actor has this relationship with.
    resolve: Callable[[Any, Any], Awaitable[set[Any]]]


@dataclass(frozen=True)
class GrantScopeSpec:
    """A kind of thing a role grant can be BOUND to — spec 91's project scope,
    RADD-791's wiki space.

    `key` names the `<key>_id` column on the grant row, so this registry does NOT
    make the set of scopes open: a new kind needs a column, i.e. a migration in
    auth. What it inverts is the KNOWLEDGE — what a scope id is called, whether
    it is real, how much of the kind an actor reaches — none of which auth can
    answer without importing the module that owns the scope.

    `reach` is optional because only a scope kind whose readability is its own
    can answer it: wiki spaces carry per-space ACLs, while project readability is
    an atom question auth answers with its own machinery.
    """

    key: str
    labels: Callable[[Any, Any], Awaitable[dict]]  # (session, ids) -> {id: display name}
    exists: Callable[[Any, Any], Awaitable[bool]]  # (session, id) -> is this a real scope
    reach: Callable[[Any, Any], Awaitable[tuple[int, int]]] | None = None  # -> (readable, total)


@dataclass(frozen=True)
class ProjectPurgeSpec:
    """Rows that must be destroyed with a project because the DATABASE will not
    do it — their `project_id` foreign key carries no `ON DELETE CASCADE`.

    Table names rather than a callback, deliberately: the value of the registry
    is that coverage can be CHECKED (tests/test_project_purge.py asserts every
    non-cascading project-scoped table is named by some spec), and a callback is
    opaque to that check. A plain DELETE is also the right verb — a purge is an
    administrative teardown of rows nobody authored, so routing it through each
    module's service would re-run permission checks and emit deletion events for
    work that never really happened.

    `tables` are deleted in the order given; `order` sequences the modules
    against each other (low first), because a table must go before the one its
    rows point at.
    """

    name: str
    tables: tuple[str, ...]
    order: int = 50


# --- page extensions (RADD-709: live blocks embedded in a page's markdown) ---
@dataclass(frozen=True)
class PageExtensionSpec:
    """An extension a page can embed as a fenced block — ```` ```radd:<name> ````.

    The kernel half is DECLARATION only: the name, how to describe it in the
    editor's insert menu, and the shape of its parameters. Rendering is entirely
    client-side (the SPA dispatches by name through its own registry), which is
    why there is no handler here — the server never renders a page body, so a
    server-side renderer would be a second implementation of something nothing
    calls.

    What this registry buys is the INSERT MENU: `GET /pages/extensions` is a
    function of what is installed, so a plugin's extension appears in the menu of
    a running Radd with no edit to the pages module, and disabling that plugin
    removes it from the menu in the same breath (the spec-94 unmount path). A
    page still holding a block whose name has gone renders an honest "unknown
    extension" card rather than raw JSON — degrading is the client's job, not a
    reason to keep a dead entry in the registry.

    `params_schema` is JSON Schema, used by the insert menu to build a small form
    and by the renderer to report a malformed block against the field that is
    wrong. It is advisory, not enforcement: a body is markdown, and markdown a
    user typed by hand must never fail to render because a parameter was spelled
    oddly."""

    name: str  # the fence suffix: `toc` for ```radd:toc
    label: str  # insert-menu title
    description: str = ""  # one line, insert-menu subtitle
    params_schema: dict[str, Any] = field(default_factory=dict)
    icon: str = ""  # lucide icon name, for the insert menu


# --- sockets (§4a: typed plugin-to-plugin integration points) ---
@dataclass(frozen=True)
class IntegrationSpec:
    """A plugin providing (or consuming) a named socket: StorageBackend, Notifier,
    Connector, AIProvider, VcsProvider, TaskBackend, AttachmentFilter."""

    socket: str
    name: str
    impl: Any = None  # provider instance/factory
    consumes: bool = False


# --- settings (§ settings: keys + admin sections owned per plugin, RADD-891) ---
@dataclass(frozen=True)
class SettingSpec:
    """A scalar cascade setting a plugin contributes — the inversion of
    `settings.types.SettingKey`'s old hardcoded catalog, mirroring
    `PermissionSpec` (RADD-890). `settings` keeps the CASCADE MECHANISM
    (resolution order project → instance → env, coercion, the
    `/scoped-settings` API) and reads this catalog instead of hardcoding every
    feature's tunables.

    `type`/`scopes` are plain strings rather than `settings.types.SettingType`/
    `SettingScope` — kernel purity forbids importing a module's enum here —
    and `settings.service` coerces via `SettingType(spec.type)` at read time,
    same as it already did for the enum form.
    """

    key: str
    type: str  # "string" | "int" | "bool" (settings.types.SettingType values)
    scopes: tuple[str, ...]  # cascade levels this key may be SET at: "instance" | "project"
    label: str = ""
    description: str = ""
    # The `config.Settings` attribute supplying the env/config default, when it
    # differs from the key itself (e.g. `ldap_user_sync_base` defaults to the
    # pre-existing `RADD_LDAP_USER_SEARCH_BASE`). "" = same name as `key`.
    config_attr: str = ""
    # Enumerated STRING settings (spec 107): the only accepted values — a write
    # outside the set 409s, and the generic settings editor renders a select.
    choices: tuple[str, ...] | None = None
    # The editor renders a masked input; the value itself stays admin-readable
    # over the settings API (RADD-846's recorded decision).
    secret: bool = False
    # RADD-930: which settings SURFACE this key belongs on — the owning plugin's
    # call, not the kernel's, and not re-derived client-side. "" = the scope's
    # General page. General renders the REMAINDER (empty sections plus any
    # section this build has no surface for), so a departed or misspelt section
    # can never make a setting unreachable — the reason it is computed by
    # subtraction rather than given a section name of its own.
    section: str = ""

    @property
    def default(self) -> Any:
        """The ultimate fallback: the instance's env/config value. Kernel's own
        domain per its charter (config/loader/lifecycle + "the settings
        platform"), so importing `radd.config` here is not a plugin dependency."""
        from radd.config import settings as _config

        return getattr(_config, self.config_attr or self.key)


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
