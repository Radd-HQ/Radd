# Spec 119 — the validation stage: intake checked by an automation graph

**.** A submission can be refused, or improved, before it becomes an issue. The
rules are an automation graph like any other — the same canvas, the same
filters, the same node registry — bound to intake and run at submit time,
against a real row inside a savepoint. What it produces is not actions: it is
**findings**, sentences addressed to the person submitting, each optionally
aimed at the field it is about.

## Why

Radd already has three ways to say a field is required, and none of them can say
what this needs to say.

- The **field registry** enforces presence and type. It cannot express "a bug
  report must name the version *and* the steps", and it cannot say it in
  sentences.
- **Form required-overrides** (spec 17) are per form and per field, with no
  conditions: "required when the priority is Blocker" is inexpressible.
- **Workflow guards** (specs 61/107) are the closest relative and the clearest
  precedent — a pure evaluator, a mode cascade, a 422 naming the failures — but
  they gate a TRANSITION. `check_transition` is not called on create at all, so
  nothing gates creation today.

And the thing that would make any of them worth having is judgement: "is this
report actually actionable?" is a question a model can answer usefully and a
field validator cannot answer at all.

Meanwhile the automation engine (spec 116) is already a DAG of filters, gates
and contributed nodes with a dry-run mode that plans without applying. The
validation rules an admin wants — *for this form; when the priority is high;
unless the reporter is internal* — are exactly what that canvas expresses. So
this spec adds no rules engine. It adds a trigger, a node, and the plumbing to
run the existing walk as a question.

## What

### The trigger and the binding

**`trigger.event` with `event: "validate"`** — a third sentinel beside `manual`
and `schedule`, deliberately absent from the event catalog so the outbox
consumer can never start a run from it. Its params ARE the binding:

- **`targets`** — a LIST of `{kind: form | issue_type | project, id}`. A list,
  because "this graph checks the incident form and the Bug type in two projects"
  is a set of scoped rows; three nullable scalar params could only ever hold the
  last one someone chose.
- **`mode`** — `advisory` (findings shown, "create anyway" allowed) or
  `required` (enforced for every non-automated caller).

Condition-based applicability needs no params beyond those. The GRAPH expresses
it: `trigger → filter.slq → matched → checks`, and an unmatched packet reaches
no check.

**`automation_validations`** (migration `d119valbind`) is that list indexed —
PK `(automation_id, node_id, target_kind, target_id)` plus `mode`, rebuilt
wholesale by `service._sync_validations` on every write, exactly like
`_sync_triggers`. Intake has to answer "is anything validating this draft" in
ONE query, on the request path, before Submit returns; parsing every stored
graph is the version that gets slower with every automation anyone writes.
`target_id` carries no foreign key and cannot — the target is polymorphic across
three owners' tables — so a deleted target stops matching rather than breaking.

### The check node

**`validation.fail`**, params `{message (required on write), field?}`. Reaching
it records a `Finding{node_id, field, message}` and passes the packet through,
so several checks chain off one branch.

It is an **ACTION kind**, not a sixth `AutomationNodeKind`. Its port behaviour
is byte-identical to every other action's — one `out` carrying its input — so a
new kind would buy a `PORTS_BY_KIND` row, a `BUILTIN_ARITY` row, an SPA
`NodeKind` member and a canvas visual to express a difference that lives
entirely in what the node DOES. That is what `type` is for.

`field` is a `BuiltinItemField` name or `cf.<key>`, checked for SHAPE only and
never against the live registry: a graph written when a custom field existed
keeps producing readable advice after someone deletes it, and simply stops
highlighting a control.

### The AI node

**`ai.validate`** (`ai/automation_node_validate.py`) — a sibling of
`ai.classify`, not a mode on it. The classifier ROUTES: enumerated answers, so
it cannot invent a branch, and it says nothing in its own words. This one
WRITES: the admin gives a quality bar in prose, `complete_structured` returns
`{passed, findings:[{message, field?}]}`, and each finding is a sentence someone
reads. A node that did both would have to decide which it was doing on every
call, and a checker constrained to enumerated answers can only say "no" without
saying why — which is the canned-message design this rejected.

Contributed nodes reach the finding collection through
**`ctx.add_finding(message, field)`**, a method on the executor's node context
rather than a list they append dicts to: `Finding` is the automations module's
vocabulary, and the nodes producing findings live elsewhere. On an ordinary
event walk nothing is collecting, `add_finding` is a no-op, and `ai.validate` is
a pure `pass`/`fail` router — the same node in both graphs with no mode switch.

**An AI outage must not silently block intake.** A provider being down is not
evidence that a submission is bad. A provider failure, a dormant feature, an
unresolvable feature gate and a node with no prompt all take the `unavailable`
port and record nothing; `on_unavailable: fail` is the deliberate opt-in for a
required-mode admin who would rather refuse than accept anything unchecked.

Findings BEAT the model's own `passed` flag — one that lists three problems and
then ticks "fine" has told us about the problems — and an unknown `field`
degrades to a general finding rather than being dropped or passed to a client
that would hunt for a control by that name.

### The savepoint flow

`POST /items/validate` (body = `ItemCreate` + `commit`):

```
begin_nested() → items.create_item(...) → validate → pass: release; fail: rollback
```

**Auto-create on pass, one round trip.** The row that was validated IS the row
that survives. It is only safe because `items.create_item` is pure DB — search,
realtime, webhooks and notifications are all outbox consumers reading committed
rows, and the `item.created` event is itself a row that rolls back with
everything else. Nothing outside the transaction can observe a draft that did
not survive.

`commit` is three values, not a boolean: `pass` (keep it if it passes), `always`
(the advisory create-anyway — **409** where any governing binding is required,
because a mode the admin chose is not something a request parameter overrules),
and `never` (a pure pre-flight).

### Enforcement everywhere else

`items.create_item` dispatches a new in-transaction hook, **`ItemHook.CREATING`**
(`items/hooks.py`), after the row is flushed with its labels and mentions and
before `_finish` emits `item.created` — the last moment a creation can still be
refused with no trace left behind. `automations/subscribers.py` registers the
handler; `items` never learns who listens, because the dependency has exactly
one legal direction and `test_module_contracts.py` refuses the cycle.

That handler is what makes a required rule a rule rather than a suggestion with
a nice interface: `POST /items`, the MCP `create_item` tool, an extension and a
script all go through it. Three skips, each a different way of not being intake:

- **the savepoint flow's own inner create** (a ContextVar, since the dispatch is
  deep inside a service that must stay ignorant of its callers);
- **`events.automated()`** — an automation's output is not somebody submitting a
  request, and a required check that refused it would break the automation;
- **`events.quiet()`** — imports. Validating history would refuse exactly the
  badly-filled-in issues the checks exist to stop being created today.

Only REQUIRED bindings run there: advisory findings have no one to show
themselves to on that path.

### The error vocabulary

`{detail: "item validation failed", findings: [{message, field}], mode}` — the
**third** 422 alongside the field registry's `{detail, errors}` and the workflow
guards' `{detail, errors, from_state, to_state}`. `findings`, not `errors`: an
error names a value the API could not accept, a finding names something a person
should go and fix, and the client renders them differently — one against a
control, one in a panel. `ValidationBlocked` subclasses `RaddError`, so the MCP
dispatcher already relays it as a readable `isError` refusal.

### The surfaces

- **`GET /items/validate/context`** → `{governed, mode}`; `mode` is null exactly
  when nothing governs, so "advisory" cannot be mistaken for "ungoverned".
  Gated on `item.create` in the project — the same atom that decides whether the
  caller could create the draft at all.
- **Forms** route through the same flow (`service._create_validated`, deferred +
  feature-detected, so a submit with `automations` absent is the one
  `create_item` it always was), passing `form_id` so a form-targeted binding
  matches. `staging.claim` already ran after `submit_form`, so a rejected draft
  never takes ownership of its files.
- **The portal** gets `{governed, mode}` on the form's OWN render payload rather
  than the items endpoint: a visitor's right to be there is the SHARE, and an
  `item.create` gate would 403 exactly the people the form exists for.
- **The New Item modal and both form pages** turn Submit into Validate where a
  graph governs, highlight the control each finding names, and show every
  finding in a shared `FindingsPanel` — including the ones already against a
  control, since one may be attached to an input the person has not scrolled to.
  "Create anyway" appears under advisory only.
- **The builder** gains a target row-builder + mode picker for the validate
  trigger, a message + field picker for the check, and `POST
  /automations/{id}/test` now returns `findings` — without which a dry run of a
  validation graph reports port counts and no actions, which is accurate and
  useless.

## Rejected

- **UI-only gating.** The rules would hold exactly as long as everyone used the
  web form. `POST /items` and the MCP tool would walk straight past them, and an
  admin who marked a check "required" would have been told something untrue.
- **A signed-receipt pre-flight** — validate, return a signed token, present it
  on the real create. Two round trips, a signature scheme, and a window in which
  the thing validated and the thing created can differ, for checks that are
  cheap to run again.
- **A draft representation in packets.** `graph.Packet` carries entity IDs, and
  every node downstream is written against rows that exist: `filter.slq`
  compiles SLQ against one real item, the AI context builder reads an
  `ItemRead`. Teaching all of that a second, draft-shaped dialect is the version
  where the check that passes at intake is not the check that would have run
  afterwards.
- **Canned messages only** — an enumerated set of refusals the admin writes and
  the AI picks between. It is `ai.classify` with extra steps, and it cannot say
  the one thing worth saying: what is missing from THIS submission.
- **Validation that mutates the draft.** Enrichment stays with ordinary
  post-create automations; a validation walk runs with `apply=False` and applies
  nothing, which is what makes "what validation saw" and "what a run would do"
  the same code with one thing switched off.

## Invariants tested

`server/tests/test_intake_validation.py` (39) and
`server/tests/test_ai_validate_node.py` (16):

- a validate trigger is indexed per target; dropping a target drops its
  governance (wholesale rebuild, never a diff);
- the write path refuses a trigger that governs nothing and a check that says
  nothing — both store as "configured" and then do nothing at all;
- resolution UNIONS project, issue type and form, and never runs one graph twice
  for a draft matching it on two axes;
- the walk collects findings and APPLIES NOTHING — an `add_label` node
  downstream of the check did not run;
- a failing draft leaves nothing behind; a clean one is kept in the same round
  trip; `commit: always` is refused with 409 under a required binding;
- a required check refuses a plain `POST /items`, and does NOT refuse an
  engine-created or an imported item;
- the savepoint flow does not validate twice;
- `ai.validate` records findings through the seam, degrades an unknown field,
  caps the count, and blocks nothing when the provider is unreachable;
- both endpoints are REACHABLE over the assembled app (RADD-761's lesson:
  `POST /items/validate` reaches its handler past `GET /items/{item_id}` only
  because a method-mismatched path is a PARTIAL match, and the context read is
  three segments because a two-segment GET would have sat behind it).

`web/scripts/intake-validation-proof.mjs` measures the flow in a browser, in
both themes, with a deterministic graph and no model: the button's wording, the
findings panel's presence, position and contrast, the control-level highlight,
"Create anyway" under advisory and its absence under required, and the pass
state closing the modal.

## Notes worth keeping

- **A universal action at SET arity fires on an EMPTY packet by design** ("nothing
  matched — tell me"). Inheriting that made `trigger → filter → matched → check`
  report its finding about a draft the filter had just EXCLUDED.
  `validation.fail` refuses to fire on an empty packet, which is what makes the
  filter-gated form mean what it reads as.
- **Rolling back a savepoint EXPIRES the states it touched**, and reading an
  expired attribute from synchronous code — which is what `project.id` inside a
  `select(...)` builder is — attempts IO outside the greenlet and raises
  `MissingGreenlet`. No call site is exposed (each reads only the verdict
  afterwards), but a test holding an ORM row across the flow was, and it read
  exactly like a product bug.
- **Contributed-node schema and permission checks ran for ACTION nodes only**
  before this spec, so every contributed GATE — `ai.classify` since spec 116 —
  could be stored with its required params blank: a node that saves cleanly,
  looks configured on the canvas, and takes its fallback port forever. Widened
  to every kind.
- **`getBoundingClientRect` said the findings panel was present, sized and at a
  positive y** while it sat several hundred pixels below the fold of a long
  modal. Every numeric check passed; the SCREENSHOT caught it. The panel now
  scrolls itself into view, and the proof asserts `y < innerHeight` rather than
  `y >= 0` — answering a click somewhere the eye is not is the same failure as
  not answering it.
