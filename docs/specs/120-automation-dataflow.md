# Spec 120 — automation dataflow: named node outputs, and one AI call that fills them in

**.** A node in an automation graph can produce NAMED VALUES, and every node
downstream can read them in the `{{token}}` vocabulary the action params already
use. `ai.generate` is the producer that makes it worth having: one model call
works out a priority, a team, a state and a sentence of advice, and four
ordinary actions write them.

The whole product claim, as one graph:

```
trigger: item.created
  → ai.generate  (named "triage": priority, team, state, advice)
      → set_priority  {{triage.priority}}
      → set_team      {{triage.team}}
      → set_state     {{triage.state}}
      → add_comment   "{{triage.advice}}"
```

## Why

The graph could already ROUTE on what a model decided and could never READ it.
`ai.classify` (spec 116) picks one of four enumerated answers, sends the packet
down that answer's port, and the value itself exists for one instant inside the
executor. To act on it you wire a branch per answer, and to act on four
independent answers you wire the product of them — twenty-four branches for a
triage that is four assignments.

Nothing in the engine was missing an idea; it was missing a place to PUT a
value. A packet carried facts (the triggering event) and subjects (entity ids).
There was no third thing: what this run has worked out so far.

Three consequences fell out of that gap and are fixed here together, because
each is unusable without the others:

- a node has no NAME, so nothing could address it even if it produced something;
- action VALUE params were literals — `set_priority` took a `Priority` on the
  wire, so a template could not have been stored in it;
- an action that could not resolve its target skipped with a message aimed at
  whoever wrote the automation, not at whoever has to fix it now.

## What

### The variable bag rides on the PACKET

`Packet.vars: {node name -> {field -> value}}`. Not on the run: branching is
exactly what makes it interesting. A value produced on a branch that was not
taken must not be readable on a branch that was, and a run-wide dict cannot
express that. Branch is a copy — the outer mapping is rebuilt on every write and
inner mappings are only ever replaced, never mutated, so a packet handed to
three downstream nodes shares them safely. Fan-in unions with the later writer
winning, and `walk` now feeds arriving packets in TOPOLOGICAL order, so "later"
means the producer that actually ran second rather than whichever edge happened
to be stored first.

Values are strings. A producer stringifies at the seam; a token renders to text
either way, and coercing once beats every consumer guessing.

### A node may be NAMED

`name` on the node dict — JSONB, no migration. It is the left half of
`{{triage.priority}}`.

Separate from `id`, deliberately. The id is machinery (`gate1`, `act3`) and is
what edges are wired to, so renaming it would be a graph-wide rewire; a name is
prose someone chose and can change freely. The rule is
`[a-z][a-z0-9_]{0,29}` — one rule shared with output names, because both halves
of `{{node.field}}` are read as one identifier, which is why it lives in the
kernel beside `OutputField` rather than in either module.

**Strict on write, lenient on read.** Three refusals on save, each because the
alternative is silent:

| refused | because |
|---|---|
| a name the token grammar cannot hold | `{{Triage Result}}` renders the braces verbatim into somebody's issue |
| two nodes with one name | the token means whichever ran later — behaviour depending on an order nobody wrote |
| a reserved root (`item`, `actor`, `payload`, …) | a node called `item` shadows `{{item.key}}` everywhere, and the token keeps resolving |

Read back, a name that is not legal simply makes the node unaddressable. A row
edited around the API degrades to a producer nobody can reference — visible in
the dry run — rather than an automation that will not load.

The reserved set is DERIVED from the served token catalogue rather than listed
beside it. A hand-kept copy would be the third place this vocabulary lives, and
the one nobody notices going stale.

### Outputs are DECLARED, exactly as ports are

`AutomationNodeSpec.outputs` / `outputs_for` / `outputs_at`, ranked by the same
static-then-dynamic rule `ports_at` uses. The reason is RADD-1064's: a client
has to list the tokens a downstream node may use BEFORE anything has run, and a
value discovered only at run time can only be offered after it is too late to
reference it.

| producer | outputs |
|---|---|
| `ai.generate` | `text`, plus one per declared field (dynamic — the outputs ARE the params) |
| `ai.classify` | `answer` — an ENUM whose choices are the configured answers |
| `action.create_item` | `key`, `id`, `url` |
| the trigger | nothing |

The trigger deliberately produces nothing: the event it carries is already the
`{{event_type}}` / `{{actor.*}}` / `{{payload.*}}` root vocabulary, and a bag
entry would be a second way to say the same thing — silently unavailable under
the manual and schedule triggers.

`create_item`'s outputs are what make "file a follow-up, then say so on the
original" expressible. `_apply_plan` now returns the item it created rather than
its id, because the id alone cannot say `TD-42`.

### `ctx.set_output(name, value)` — the seam

Shaped like spec 119's `add_finding`: the node says what it produced, the
executor decides what can be done with it. A name outside the identifier rule is
dropped with a warning — a value nothing could ever reference is not a value.

The values a node produced ride on EVERY port it emits, not one. `create_item`'s
`out` carries the items that caused the new issue and `created` carries the new
issue; both are places someone legitimately wants `{{followup.key}}`, and a rule
that picked one would make which one a thing to remember.

**A PER-ITEM invocation publishes nothing.** N items produce N answers and the
bag has one slot per node, so `{{classify.answer}}` could only ever name one of
them, silently. A token that misses is a recorded skip; a token that resolves to
some other item's answer is a wrong write nobody notices. This is the reason
`ai.generate` is fixed at SET arity: per item it would produce values and drop
them, which is a node that looks configured and whose every downstream token
misses. A per-item bag is a real future change — it needs a dimension on the
packet and on every render site — and it is not this spec.

### One resolver, one vocabulary

`{{item.key}}`, `{{actor.name}}` and `{{payload.…}}` keep meaning exactly what
they meant. `{{<node>.<field>}}` joins them in the SAME resolver, reading the
bag. There is no second template syntax.

`Renderer` replaces the bare `render_template` call inside the planner because
rendering now has to report on itself: the text, what each token BECAME (so the
dry run can show `{{triage.priority}} → high` rather than making someone infer
it), and which VARIABLE tokens found nothing.

**Every OTHER unresolvable token still degrades verbatim**, deliberately.
`{{payload.foo}}` on an event that does not carry `foo` is a normal miss on a
shape that varies per event; turning that into a skip would silently disable
working automations. A variable token is different: it names a node the author
wired, and if that node did not run, acting anyway is the wrong write.

### Tokenized VALUES, and skips that say what to fix

Every item-bound action's named target renders as a template before it resolves
— state, priority, assignee, team, cycle, release, label, custom-field value,
and `create_item`'s priority. The RENDERING is the only new step: resolution
still goes through the by-NAME seam that was already there, which is what keeps
an automation written against a project's vocabulary working when the rows
behind it are recreated.

`SetPriorityParams.priority` and `CreateItemParams.priority` became strings with
a check rather than the `Priority` enum, because the enum on the wire refuses
`{{triage.priority}}` before it can render. What it renders to is still measured
against the enum — in the planner, where the failure is a recorded skip.

Three ways an action now declines, each with the reason:

1. **a variable token found nothing** — `{{triage.priority}} — no node named
   'triage' produced anything on this branch`, or `'triage' produced priority,
   team, not 'urgency'`. This OVERRIDES whatever else the planner concluded: a
   missing `triage` would otherwise report "no state '{{triage.state}}' in TD",
   which sends the reader to the workflow settings for a problem in the wiring.
2. **the rendered value is outside the vocabulary** — `'Blocked' is not a state
   in TD (states: Triage, In Progress, Done)`. Built ONLY from a list the
   planner already had in hand. A skip is the unhappy path already, and paying a
   round trip to phrase it better is how a nightly run over 200 items gets
   slower every time something is misconfigured — so assignee and release get no
   hint, because there is no list there to print.
3. **a workflow guard refused the transition.** It always applied to automations
   by design (specs 61/107 are explicit that predictability beats convenience),
   but the `TransitionError` landed in the executor's generic `except Exception`
   — logged as a crash, and reported by the dry run as an action that "would
   apply" and never could. It now rewrites the plan just recorded, so there is
   one record per invocation carrying the guard's own sentences.

### Write-time refusal of a dangling reference

A save whose token names a node that is not in the graph is refused, naming the
token AND the node holding it. Renaming the producer and leaving the consumer
behind was otherwise an action that quietly stops happening at 3am.

Two deliberate limits. UPSTREAM-ness is not checked: a graph mid-build has every
right to a producer that is not wired yet, the editor's picker offers only
reachable producers anyway, and a token whose producer never ran is a recorded
skip at run time. And a producer that declares NO outputs accepts any field —
refusing there would punish a plugin's user for the plugin's silence.

### `ai.generate`

The third AI node, and the one the other two make sense of by contrast:

| node | does |
|---|---|
| `ai.classify` | ROUTES. Enumerated answers ARE the ports; it says nothing in its own words |
| `ai.validate` | WRITES PROSE at a person — findings, shown to whoever submitted |
| `ai.generate` | FILLS IN FIELDS — named values the rest of the graph reads |

Params: a `prompt` (≤2000), the shared `include` toggles, and `fields` — up to
eight `{name, kind: text | enum, choices}`. One `complete_structured` call
builds a schema from them, with every enum field a JSON-Schema enum, so the
model literally cannot answer outside the list. That is the classifier's safety
property applied per field instead of per node. An enum declared with no choices
degrades to text: "choose one of nothing" produces free prose under a name that
promised a vocabulary.

`text` is always produced alongside the declared fields — "explain the call" is
the commonest thing anyone wants beside the values.

**No `on_unavailable`.** Unavailability is a PORT. The model did not answer, so
no values were produced, so every token that would have read one misses and its
action records a skip. A graph that wants to do something about it wires
`unavailable`, which is strictly more expressive than a setting. Every failure
path — no prompt, out of time, the toggle off, the provider down, a reply with
nothing usable in it — takes that port and publishes NOTHING, so an outage can
never leave half a bag behind.

**A GATE kind, and the executor is the reason.** By what it does this is an
action. But a contributed ACTION cannot name the port it leaves by:
`executor._run_action` returns what it created and `_run_node` emits `out`
unconditionally, so an `unavailable` port on an action would be a handle wired
to a branch that never fires. A gate's `plan` returns its port, which is exactly
the mechanism this needs, and `ai.validate` already sits there for the same
reason. Teaching the executor to let a contributed action route is the better
long-run answer and a change to the heart of the walk; it is not this spec.

`AiFeature.GENERATION` is wired into all three registries the RADD-989 test
guards, plus a Settings → AI toggle. Its help copy carries the injection caveat:
what comes back is influenced by text a submitter wrote, and a generated comment
posts unmarked — marking it would be a lie in the other direction on an instance
where the admin wrote the prompt and trusts it.

### The builder

Six surfaces, each of which was otherwise a way to build a chain that saves
cleanly and does nothing.

- **A producing node arrives NAMED** — `generate_1` from its type plus a
  counter. Auto-naming is the CLIENT's job: the server has no opinion about what
  a node should be called, and a producer that arrives unnamed is a node whose
  whole point is unreachable until someone notices the field. The name field
  appears only where naming buys something, validates as it is typed against the
  same three rules the server applies, and shows what the node will be read as.
- **The canvas shows the name.** Reading a graph means knowing which node
  `triage` is.
- **The token picker is TOPOLOGY-AWARE** — it walks the edges BACKWARDS and
  lists only producers that can reach the node being edited, only named ones,
  only their declared outputs, above the unchanged event roots. Listing every
  named node would offer values from branches that never run with this one:
  tokens that compile, save, and resolve to nothing.
- **Clicking a token inserts it** into whichever field was focused last. One
  `onFocusCapture` on the inspector rather than an `onInsert` threaded through
  four param editors including the generated one.
- **Value params have a TOKEN MODE**, opt-in per param. Degrading every dropdown
  into a text field would cost everyone the affordance to buy a minority the
  flexibility — and would lose the vocabulary, which is what stops a typo
  becoming a 3am skip.
- **`ai.generate` gets a bespoke form.** Its central param is an array of
  objects whose shape varies per row, which is the case `SchemaFields`' own
  docstring names as "ship your own component". The generic form still renders
  the prompt and the include toggles, so there is one copy of those.

The dry run reports the dataflow: per node, what it produced and the token that
reads each value — shown even when the node is unnamed, with the token blank,
because that is the mistake it exists to surface; per action, what each token
became and, when it skipped, the reason in full.

### RADD-1074 — what a validation graph says about its findings

A separate bug in the same wave, and the same class of problem: a finished graph
that looks unfinished.

In a graph whose trigger is `validate`, a finding is not a branch — it IS the
intake verdict, delivered to whoever submitted. The empty handle under
`ai.validate`'s `fail` port therefore read as an unwired branch, and people went
looking for the action that sends the feedback. So on a validate-triggered graph
only:

- the finding-producing ports (`ai.validate` `fail`, `validation.fail` `out`)
  carry a "→ feedback to submitter" note on the card;
- an UNWIRED one is drawn as a deliberate CAP — larger, filled, bordered —
  rather than the same small stub every unwired port has, so the eye stops there
  instead of hunting;
- the inspector says the sentence: findings are delivered automatically, and
  wiring anything after the port is optional.

None of it appears on a graph that is not validate-triggered, where the same
node really is a plain pass/fail router and the badge would be a promise nobody
keeps.

## Where

| file | what |
|---|---|
| `kernel/specs.py` | `OutputField`, `OutputKind`, `OUTPUT_NAME_RE`, `AutomationNodeSpec.outputs*` |
| `automations/graph.py` | `Node.name`, `Packet.vars`, `with_vars`, the merge rule |
| `automations/nodes.py` | `outputs_of`, `output_name` — the one ranking |
| `automations/types.py` | `BUILTIN_OUTPUTS` |
| `automations/executor.py` | `set_output`, `_stamp`, topo-ordered fan-in, `_Outcome`, the guard-refusal record |
| `automations/templating.py` | `Renderer`, `reserved_roots`, the public `TOKEN_RE` |
| `automations/planning.py` | tokenized values, vocabulary hints, the miss-overrides-skip rule |
| `automations/service.py` | `_check_names`, `_check_token_references` |
| `ai/automation_node_generate.py` | the node |
| `web/src/lib/automation-outputs.ts` | outputs, the backwards walk, name rules |
| `web/src/components/automations/GenerateFields.tsx` | the bespoke form |
| `web/scripts/automations-dataflow-proof.mjs` | the chain, end to end, against a fake at the HTTP layer |

## Done when

- a node's declared outputs are addressable by name from any node downstream of
  it, in the same `{{…}}` vocabulary the action params already render;
- a token that resolves to nothing SKIPS its action with a reason naming the
  token, and every other action on the branch still runs;
- a rendered value the project does not have skips with the vocabulary it
  measured against, and a workflow guard's refusal reads the same way;
- one `ai.generate` node feeds four actions and the dry run shows every value it
  produced and every token it resolved;
- a validate-triggered graph says where its findings go, and an unwired finding
  port looks finished.

## Not built

- **A per-item variable bag.** Producers at ITEM arity publish nothing rather
  than publishing one item's answer for all of them.
- **A contributed ACTION that names its outgoing port.** The reason
  `ai.generate` is a gate.
- **Any use of the produced values outside `{{…}}`** — no arithmetic, no
  conditions on them. A gate that tests `{{triage.priority}}` is expressible
  today only by an action that reads it; testing values is the obvious next
  question and it belongs to the filter/gate vocabulary, not here.
