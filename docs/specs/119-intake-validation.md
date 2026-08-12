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

What it may NOT hold is an event gate. `gate.event`, `gate.field_changed` and
`gate.changed_by` read the event that started the run — its diff, its actor —
and a validation run has none: the facts are synthetic, so each of those answers
a constant and the branch behind the port it never takes is a check that looks
configured and can never fire. They are refused on write, exactly as a gate
under a SCHEDULE trigger already was, and the refusal is scoped to what THIS
trigger can reach so a graph holding both a validate trigger and an event
trigger keeps the gates on the event branch. `gate.state_category` is not in
that set — a draft has a state, and asking about it is a real question — and
neither are the contributed gate-KIND nodes, `ai.classify` and `ai.validate`,
which is the whole point of the kind.

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

**Collecting is read off the TRIGGER, not passed in.** `executor.walk` decides
it from the trigger node it starts at (`event == "validate"`), which means a
validate-trigger graph collects on every walk — the intake path, a manual run,
the rule test panel's dry run — and no other graph collects on any. Deriving it
was a correction: the first build handed the report's list to every walk, so a
`validation.fail` wired into an event graph accumulated findings nobody would
read and `preview`'s `matched` went true for a graph that would apply nothing.
The claim in this document was always the design; the executor is now what it
says.

**An AI outage must not silently block intake.** A provider being down is not
evidence that a submission is bad. A provider failure, a dormant feature, an
unresolvable feature gate and a node with no prompt all take the `unavailable`
port and record nothing; `on_unavailable: fail` is the deliberate opt-in for a
required-mode admin who would rather refuse than accept anything unchecked.

Findings BEAT the model's own `passed` flag — one that lists three problems and
then ticks "fine" has told us about the problems — and an unknown `field`
degrades to a general finding rather than being dropped or passed to a client
that would hunt for a control by that name.

**The include toggles bound the input, not the output**, and the node's help
text now says so. "Reads run as the automation's identity, so the prompt can
only contain what it could already see" is true and is only half the boundary:
that identity is usually WIDER than the submitter's, an upstream `search.slq`
reads as the automation's author, and a finding is rendered to whoever submitted
— a portal visitor included. Anything put in front of the model can come back
quoted in a sentence someone outside the team reads. What you include is
readable by the person submitting; that is the rule, and it is one an admin has
to be told rather than left to infer from a sentence about reads.

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
(the advisory create-anyway — **409** where a required graph produced a finding,
because a mode the admin chose is not something a request parameter overrules),
and `never` (a pure pre-flight).

**A finding carries the mode of the graph that produced it**, and `blocks` means
"a REQUIRED graph objected". The first build aggregated `mode` over every
governing graph and asked "are there findings and is the mode required" — which
refused a draft that satisfied every required graph and only tripped an advisory
one, while `POST /items` (whose enforcement path runs the required bindings
alone) accepted that same draft. The button and the API disagreed about the same
rules. The verdict's `mode` is still the strictest, because that is what the
client shows before anything has been submitted; what refuses a creation is read
off the findings themselves. Truncation inherits the strictest mode of what it
dropped, so a wall of advice can never demote a required refusal.

**Two things bound the walk, because it runs inside the create's transaction.**
That transaction holds the project's number lock (`_resolve_number`), so for as
long as the checks run, every other creation in that project waits — an AI check
is up to `ai_timeout_seconds` (30s) of that, per governing graph.

- **A wall-clock budget for the whole verdict** (`intake_validation_budget_seconds`,
  25s — deliberately under the AI timeout so it bites first). Past it, a check
  that costs a model round trip resolves per its own `on_unavailable`, which
  defaults to letting the draft through: an overloaded provider must not become
  a closed intake. Cheap deterministic checks are unaffected — they cost
  microseconds, and stopping them would make the findings depend on the clock.
- **Each graph walks inside its own savepoint**, with a `SELECT 1` before the
  release. The executor swallows a contributed node's exception by design, and a
  DBAPI error swallowed that way leaves Postgres in an aborted transaction:
  `ROLLBACK TO SAVEPOINT` is legal there and `RELEASE SAVEPOINT` is not, so
  discovering the abort by failing to release leaves a connection only a full
  rollback can clear. The probe buys a recovery point, and the caller gets
  **`ValidationUnavailable` → 503** — deliberately not the 422, which would tell
  someone their submission was wrong when nothing about it was.

Restructuring so the lock is not held across a model call is real work and is
filed as **RADD-1062**; the budget is the honest bound in the meantime, and this
paragraph is here so nobody discovers the serialization from a graph.

### Enforcement everywhere else

`items.create_item` dispatches a new in-transaction hook, **`ItemHook.CREATING`**
(`items/hooks.py`), after the row is flushed with its labels and mentions and
before `_finish` emits `item.created`. `automations/subscribers.py` registers the
handler; `items` never learns who listens, because the dependency has exactly
one legal direction and `test_module_contracts.py` refuses the cycle.

**The insert through the dispatch runs in its own savepoint**, and a handler
that raises rolls back to before the insert. The first build relied on the
caller's transaction being abandoned, which is true of an HTTP request and false
of anything that catches and carries on — the Jira importer's per-issue
`except Exception` records a skip and commits the batch, so a refused draft
became a half-created orphan: a row with labels, no `item.created` event, and
therefore invisible to search and every other consumer. "Nothing is left behind"
is now a property of `create_item` rather than of who calls it.

That handler is what makes a required rule a rule rather than a suggestion with
a nice interface: `POST /items`, the MCP `create_item` tool, an extension and a
script all go through it. Four skips, each a different way of not being intake:

- **the savepoint flow's own inner create** (a ContextVar, since the dispatch is
  deep inside a service that must stay ignorant of its callers);
- **`events.automated()`** — an automation's output is not somebody submitting a
  request, and a required check that refused it would break the automation;
- **`events.quiet()`** — imports. Validating history would refuse exactly the
  badly-filled-in issues the checks exist to stop being created today. The Jira
  importer also asks for the suppress scope in its own right, because quiet is a
  per-plan option and "this is history" is not;
- **machine intake** — the mail poller and the Alertmanager receiver, each
  wrapping its create in `intake.suppressed()`, which is public for exactly this.
  Neither has a channel to answer through. The poller marks the message Seen, so
  a refusal drops a customer's request with no issue, no bounce and nothing but
  a log line; the receiver answers Alertmanager with a 5xx it retries forever.
  Machine intake is not human intake: a check written for a person filling in a
  form cannot be answered by a monitoring system. **Bouncing the findings back
  by mail is a real feature and an explicit non-goal here** — it needs a reply
  template, a loop guard and a story for what happens when the sender fixes
  nothing, and shipping the refusal without it would be the worse half.

Only REQUIRED bindings run there: advisory findings have no one to show
themselves to on that path.

**The handler has its own lifecycle.** `HookRegistry.on()` appends and nothing
takes it back, so hot-disabling the automations plugin left required validation
enforced by a handler nobody could reach to unregister. `subscribers.enable` /
`disable` ride on the plugin's `on_startup`/`on_shutdown`; the flag defaults to
ON so a caller that never runs the lifecycle behaves as it always did, and only
an explicit disable turns it off.

### The error vocabulary

`{detail: "item validation failed", findings: [{message, field}], mode}` — the
**third** 422 alongside the field registry's `{detail, errors}` and the workflow
guards' `{detail, errors, from_state, to_state}`. `findings`, not `errors`: an
error names a value the API could not accept, a finding names something a person
should go and fix, and the client renders them differently — one against a
control, one in a panel. `ValidationBlocked` subclasses `RaddError`, so the MCP
dispatcher already relays it as a readable `isError` refusal.

Its sibling is `ValidationUnavailable` → **503 `{detail}`**, with no `findings`
key at all: the checks broke, which is not the submitter's problem and not
something they can fix, and a client must not be able to mistake an outage for a
clean verdict.

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

`server/tests/test_intake_validation.py` (51) and
`server/tests/test_ai_validate_node.py` (20):

- a validate trigger is indexed per target; dropping a target drops its
  governance (wholesale rebuild, never a diff);
- the write path refuses a trigger that governs nothing and a check that says
  nothing — both store as "configured" and then do nothing at all;
- resolution UNIONS project, issue type and form, and never runs one graph twice
  for a draft matching it on two axes;
- the walk collects findings and APPLIES NOTHING — an `add_label` node
  downstream of the check did not run;
- findings are the VALIDATE trigger's output and nothing else's: the same check
  under a manual trigger records nothing and a dry run of it reports no match,
  while a validate-trigger graph still reports its findings on a dry run;
- an advisory finding does NOT refuse a draft that satisfied the required graph
  governing it beside — and the plain `POST /items` path agrees;
- an event gate is refused on write under a validate trigger, on that trigger's
  branch only;
- a walk that aborts the transaction is a 503 with a usable session behind it,
  not a 500 from releasing a savepoint;
- a failing draft leaves nothing behind; a clean one is kept in the same round
  trip; `commit: always` is refused with 409 under a required binding;
- a required check refuses a plain `POST /items`, and does NOT refuse an
  engine-created or an imported item, or an Alertmanager webhook's issue at its
  real call site;
- a refusal leaves the session clean for a caller that CATCHES it and carries on
  — the importer's shape, and where the orphan came from;
- disabling the plugin disables the enforcement, and re-enabling restores it;
- the savepoint flow does not validate twice;
- `ai.validate` records findings through the seam, degrades an unknown field,
  caps the count, and blocks nothing when the provider is unreachable or when
  the walk's budget is spent — the two-graph property is asserted against the
  REAL `_NodeContext`, built by the executor's own factory, because the version
  that used a stand-in with an invented `collecting` flag was testing an
  if-statement in the test file;
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
