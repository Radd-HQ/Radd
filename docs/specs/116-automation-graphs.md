# Spec 116 — Automations become graphs

## The problem

An automation today is a **linear pipeline with one decision point**:

```
trigger → event_conditions (all/any/none over the EVENT) → condition_slq (per-item) → [every action]
```

`AutomationRule` stores that as three columns — `event_conditions` (a nestable tree),
`condition_slq` (a string) and `actions` (a flat list). Every action in the list runs
against every item that survived the filter. There is no way to say *"for the high
priority ones notify the lead, for everything else add a label"* without building two
rules that re-evaluate the same trigger and re-run the same query.

That is the reported gap: **actions cannot be attached to a condition.** Everything else
in this spec follows from fixing it — once actions hang off branches, the rule stops being
a list and becomes a graph, and a list editor stops being able to show it.

## The model

Four node kinds. The count matters: the obvious design has three (trigger, condition,
action) and it is wrong, because "condition" is doing two unrelated jobs.

| Node | In | Out ports | Semantics |
|---|---|---|---|
| **Trigger** | — | `out` | Starts the graph. Emits the event facts and the initial item set. Exactly one per graph. |
| **Filter** | items | `matched`, `unmatched` | A predicate over **each item's current state**. Narrows the set. Chaining narrows further. |
| **Gate** | items | `true`, `false` | A boolean over the **event facts** — who acted, which fields changed, old → new. The item set passes through untouched. |
| **Action** | items | `out` | Does work, then passes its input through unchanged so chains continue. |

### Why Filter and Gate are different nodes

The schema already draws this line and it has earned its keep: `condition_slq` answers with
a **subset**, `event_conditions` answers **once, true or false**. "Was this changed by a
member of the QA team" is not a property any single item has — it is a property of the
event. Modelling both as one "condition" node produces a node whose ports mean different
things depending on what you configured, which is unteachable and untypeable.

The payoff for splitting them is that **a per-item if/else needs no third concept**: it is
a Filter with both ports wired.

```
Filter(priority = high) ──matched──→ Action(notify lead)
                        ──unmatched→ Action(add label "routine")
```

### What flows on an edge

A **packet**: `(event facts, item set)`. Not items alone — actions template `{{tokens}}`
off the event and gates evaluate on it, so an items-only edge breaks both.

### Empty sets propagate; nodes declare what they need

An empty match does **not** halt the branch. The packet flows on carrying an empty set,
and each node declares whether it needs items:

- Item actions (`set_state`, `add_comment`, …) skip on empty, with a log line.
- Universal actions (`send_webhook`, `send_email`, `post_chat`, `notify_user`) still run.

The alternative — halt on empty — is the more obvious rule and was rejected deliberately.
Today's universal actions run itemless **on purpose**, and *"nothing matched today, tell
me"* is a real automation that halting makes inexpressible. A branch that genuinely should
stop on empty says so by wiring only the `matched` port, which is explicit rather than
ambient.

### Execution

- The graph is a **DAG**. Cycles are rejected on write, not at run time.
- **Fan-in unions**: two edges into one node merge their item sets, deduplicated by id.
  This is safe because both packets come from the same run, so their event facts are
  identical by construction.
- Nodes execute in **topological order**, so side effects are deterministic.
- The **loop guard is unchanged**: actions still run as `SYSTEM_ACTOR_ID`, so events they
  emit are skipped by event-triggered automations. Chaining inside a single run is not
  re-entry.

### Budget, and saying so

A linear rule costs `items × actions`. A graph costs `items × nodes × fan-out`, and the
ceiling has to be real: a per-run cap on node executions and on item-actions.

**A truncated run must report that it truncated.** Silent capping is the failure mode this
codebase keeps finding — a run that quietly did less looks identical to a run that had less
to do. The run record names what was dropped and why.

## Vocabulary

The entity is an **Automation**; its shape is a **graph** of **nodes** and **edges**.

It is deliberately **not** called a workflow. `radd.modules.workflow` already owns item
states, transitions and guards — the thing a project's board columns are made of. A second
"workflow" meaning "automation graph" would collide with the most established noun in the
product.

`AutomationRule` becomes `Automation`. "Rule" stops being accurate the moment the thing
branches.

## Plugin-contributed nodes

A node type is a kernel contribution, following the two precedents that already exist:

- **`PageExtensionSpec`** for the declaration-plus-JSON-Schema shape. Its `params_schema`
  already drives a generated config form on the client (`extension-schema.ts`,
  `ExtensionConfig.tsx`), and `GET /pages/extensions` already makes a menu a function of
  what is installed, with plugin unmount removing entries in the same breath.
- **`McpToolSpec`** for the server half: a declaration that carries its handler and its
  permission atom, dispatched by the kernel, where the spec *is* the annotation.

```python
@dataclass(frozen=True)
class AutomationNodeSpec:
    key: str                      # "filter.slq", "action.create_item", "acme.notify_oncall"
    kind: AutomationNodeKind      # TRIGGER | FILTER | GATE | ACTION
    label: str
    description: str = ""
    params_schema: dict[str, Any] = field(default_factory=dict)  # JSON Schema → generated form
    ports: tuple[str, ...] = ("out",)      # FILTER: ("matched","unmatched"); GATE: ("true","false")
    needs_items: bool = True               # False → runs on an empty set (universal actions)
    permission: str | None = None          # atom required to USE this node in an automation
    plan: Callable[..., Awaitable[list[Plan]]]
```

**A node contributes a planner, not an applier.** `planning.py` already separates deciding
what to do from doing it, which is what makes the engine testable — and it hands us
**dry-run over a whole graph for free**. On a branching automation that is not a nicety:
seeing what a graph *would* do is how anyone will trust it before enabling it.

Node UI: the generated form from `params_schema` by default; a plugin may override with its
own component through the spec-94 slot registry, exactly as view types and dashboard widgets
already do.

## Storage and migration

`automations.nodes` and `automations.edges` (JSONB) replace `event_conditions`,
`condition_slq` and `actions`.

Every existing rule is a **linear graph**, so the migration is mechanical and lossless:

```
Trigger(trigger, schedule) → Gate(event_conditions)?ᵗʳᵘᵉ → Filter(condition_slq)?ᵐᵃᵗᶜʰᵉᵈ → Action* (in position order)
```

The optional nodes are omitted when the source column is empty or NULL. The old columns are
then **dropped** — no dual-read, per the no-backcompat-until-V1 rule.

## The editor

`@xyflow/react` (React Flow), **lazy-loaded on the automations route** — the SPA bundle
already warns at 1.28 MB and a canvas library has no business loading for people editing a
board.

Taking a dependency here is a considered exception to the "the chrome is ours" line that
RADD-745 drew when it deleted Crepe. The cases differ: Crepe imposed visual chrome we spent
a release fighting, whereas React Flow is an unstyled canvas primitive — pan, zoom, edge
routing, port hit-testing, selection — and every pixel of node rendering stays ours. The
alternative is weeks rebuilding edge routing and zoom, with real keyboard-accessibility
obligations, to own something nobody sees.

## Folding in RADD-903

The sponsored recurring-tickets request lands inside this model rather than beside it:

- **Monthly and cron schedule kinds** are `radd/schedule.py` math, consumed by the
  **Trigger node's** params. Orthogonal to the graph; shared with spec 99's backup schedules.
- **The richer `create_item` fields** (assignee, type, labels, team, parent, estimate, cycle)
  become the **`action.create_item` node's** `params_schema`.

Nothing is built twice, which is why the graph is designed first.

## Addendum — node arity (RADD-918)

The four kinds above quietly assumed that **how often a node runs** is implied by **what
kind of node it is**. It is not, and separating the two is what makes the model finish.

A node declares its **arity**:

- **SET** — runs once, seeing the whole packet. A router sends the packet down ONE port;
  an action fires once.
- **ITEM** — runs once per item. A router **partitions** the set across its ports (each item
  leaves by the port its own answer names); an action fires once per item.

### Why not a loop node

The obvious request is "run this per item", and the obvious design is a loop construct.
Both ways of building one are wrong here:

- **A back-edge** (n8n's shape) is a cycle, and cycles are rejected on *write* — which is
  precisely what turns "hung consumer" into "validation message next to the edge".
- **A nested scope** keeps the DAG but makes the executor re-entrant: `emitted` becomes
  per-iteration, budgets nest, and every run-report entry grows a dimension.

Neither is needed, because in a dataflow model over SETS "for each" is not control flow —
it is how a node reads its input. An action passes its input through unchanged either way,
so arity on an action has no effect on graph SHAPE; and a per-item router is a *partition*,
which `filter.slq` already was. The one thing this genuinely cannot express is SEQUENTIAL
iteration — accumulators, "stop after the first success" — and nothing in a tracker
automation has wanted it.

### The taxonomy shifts, slightly

"Why Filter and Gate are different nodes" above argued that a gate answers ONCE. That was
right about the UX and wrong to tie it to the kind: a classifier's ports mean the same
thing at both granularities ("the items the model answered X about"), and only the
granularity of the answer moves. Filter and Gate stay separate **on the canvas** because
they teach different things; underneath they are one implementation, and `_split` and the
`ITEM_ACTIONS` branch collapsed into one partition path and one fan-out path.

### Defaults, so nothing migrates

`ACTION_ARITY_DEFAULT` reproduces the pre-arity `ITEM_ACTIONS` split exactly, and the
frozenset is now *derived* from it. A stored node with no `arity` param runs as it always
did. Five actions offer the choice (`create_item`, `send_email`, `send_webhook`,
`post_chat`, `notify_user`), plus `ai.classify`; the gates are fixed at SET because they
read `EventFacts`, where per item would be N identical answers.

### What it fixed on the way

Three failures fell out of building it, each invisible in the way that matters — a saved,
enabled automation that never did anything:

1. **A contributed node's ports could never be wired.** `graph.parse` coerced every edge
   port through `NodePort`, so an edge to a classifier's `bug` port was rejected before
   `validate` asked the node — which is the entire reason `ports_for(params)` exists.
2. **A gate fired the branch it did not take.** The untaken port emitted an EMPTY packet,
   and universal actions ignore emptiness by design. `gate → false → "nobody touched it"`
   sent that mail on every run where somebody had. A gate now emits only the port it took;
   a FILTER still emits both, because an empty subset is a real answer.
3. **`{{item.key}}` was blank on every universal action** — they were all passed
   `item=None`. A set-arity action over exactly one item now receives it.

The "empty sets propagate" rule above survives, but it was conflating two empties: *"the
filter matched nothing"* (a real answer, still propagates) and *"this branch was not
taken"* (now absent from the emit map entirely).

## Addendum — the search node (RADD-919)

Every kind in the model above can only NARROW what the trigger handed it. So an
automation's reach was bounded by the event, and only a SCHEDULE trigger could produce a
set at all — through a `query` param on the trigger node, which is this feature wearing a
disguise, available to one trigger type and buried in a form.

`source` is the fifth kind, and `search.slq` its first type: run an SLQ query when reached,
emit what it finds. Any trigger, several per graph, visible on the canvas. REPLACE by
default (ADD offered) because a silent union makes the result depend on whatever the
trigger happened to carry; an empty query finds NOTHING, because a half-filled form is the
likeliest source of one. It shares `search.find_items` with the scheduler, so "compile,
cap, log the truncation" exists once.

A new kind rather than a filter variant: a filter whose `mode` turned it into a producer
would be a node whose ports mean different things depending on its config, which is the
thing the kind split exists to prevent.

## Addendum — seeing the thing (RADD-921)

The phases below promised a dry run "per node". What shipped reported one boolean and a
flat list of actions — the shape of a linear rule — and required a seed item, which made
a search- or schedule-fed graph the one kind that could not be checked at all. Two gaps,
both of the same species: the model was expressive and opaque.

**What an event carries.** Every condition names a path into a payload, and nothing said
what any payload contained. `GET /automations/samples/events` flattens recent REAL events
into dotted paths with the values seen at each. Sampled rather than written down: a
hand-authored example per event type is a second copy of a shape defined across twenty
modules' `emit` calls, it drifts silently, and a payload that looks right and isn't is the
exact failure this exists to prevent. An event type that has never fired here gets no
sample and says so — a fabricated shape would be worse than nothing, because it would be
believed.

**What each node emitted.** `RunReport` keeps the item ids that left each port, and the
result reports every node, including the ones that never ran. The distinction the whole
panel turns on:

| | means |
|---|---|
| port emitted **0 items** | a filter matched nothing — the branch ran |
| port **not emitted** | a gate's untaken branch — it never ran |

They send someone looking in different places, so they render differently. This is the
same distinction the arity addendum introduced into the emit map, surfaced.

## Phases

1. **Execution model** — node kinds, packet, DAG validation, topological executor, budgets;
   the migration; old columns dropped. No UI change beyond keeping the existing editor able
   to express a linear graph.
2. **`AutomationNodeSpec` registry** — the kernel contribution, core nodes moved onto it,
   `GET /automations/nodes` as a function of what is installed.
3. **The graph editor** — React Flow canvas, generated param forms, plugin node UI slots.
4. **Dry-run** — execute the graph with appliers off; show per-node item counts and the plan
   each node would produce.

## Done when

- An automation can attach different actions to different branches of a condition, without
  duplicating the trigger or re-running the query.
- A filter chain narrows progressively, and an empty set still reaches universal actions.
- A plugin ships a node type that appears in the palette of a running Radd with no host edit,
  and disappears when the plugin is disabled.
- Every existing rule survives the migration with identical behaviour.
- A dry-run shows what a graph would do, per node, before it is enabled.
- An action can be told to run once for the whole set or once per item, and a router set
  to per item partitions its input across its ports.
- An automation can reach issues its trigger never named.
