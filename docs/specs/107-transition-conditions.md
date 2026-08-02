# Spec 107 — Mature transition guards: structured conditions + per-entry approvals

User ask (dogfooding the spec-61/71 editor): the approvers UI rendered EVERY
active user as a checkbox pill (~1,000 after the AD import) instead of the
compact pickers grants/teams/scope use; "Approvals required: N" was one global
count across a flat electorate — meaningless unless the subjects are a team;
the enforcement dropdown showed the raw wire strings `off/guards/strict` with
no explanation; and "Fields set" was a checkbox list (custom fields only, one
semantics) where fields should be added individually with a chosen condition —
"a more mature approval system".

## The rule model (workflow module)

The five legacy presence checks (require_assignee / require_estimate /
require_team / require_comment / require_fields) collapse into ONE check:

- **`require_field`** `{kind: builtin|custom, key, op, values?, display?, type?}`
  — `BuiltinField` covers assignee/reporter/team/priority/labels/type/kind/
  cycle/release/start_date/target_date plus the `estimate`/`comment` specials
  (their data lives in timelogging/comments; they answer set/empty only, but
  ride the same shape so the editor shows ONE condition list). `ConditionOp` =
  `set | empty | is | is_not | gte | lte`, with a per-field allowed subset
  (dates take bounds, not equality; booleans take `is`; numbers take both;
  `is_not` passes on empty — nothing isn't the value). Write-validation 409s
  unknown fields/ops, enum-checks priority/kind values, ISO-parses dates,
  float-parses numbers, and SNAPSHOTS the custom field's registry `type` into
  params (comparison + phrasing at eval time, rename-proof). `values` carry
  ids/raw values; `display` carries the human names for the failure strings
  ('"Priority" must be one of High, Urgent') — the four presence specials keep
  their legacy strings ("an assignee is required" …). `ItemSnapshot` grew a
  normalized `builtin` map (ids/enums as strings, dates ISO, labels a list,
  estimate bool-or-None, comment count-or-None) — labels/estimate/comment
  resolve lazily, only when a rule asks.

- **`require_approval`** `{approvers: [{kind: user|team, id, name, required?}]}`
  — per-ENTRY rules: every listed person must approve personally; a team entry
  needs `required` approvals from its CURRENT members; entries AND together.
  The old "N of the whole flat electorate" is gone (the user's point: it was
  useless outside a team). Subjects are write-validated (users active, teams
  exist, no dupes, team `required >= 1`) and display names snapshot
  SERVER-side — never trusted from the client. The guard failure now names
  the rules: "approval required (Hussein Jarrar; 2 of DevOps)".

## Approvals module

`approval_requests` collapses its three snapshot columns into one `approvers`
JSONB of the same entries. Satisfaction: each entry's electorate resolves live
(user → that person; team → current members; a deleted or shrunk-below-
required team makes its entry UNSATISFIABLE — deliberate: removing people
must never quietly lower an approval bar; cancel the request or edit the
rule). `ApprovalRequestRead` gained `entries` (per-entry
required/approved_count/satisfied) beside the flat resolved electorate;
`required` is gone. Event payloads swap `required` for `approvers_summary`
("Hussein Jarrar; 2 of DevOps") which notifications render verbatim. The
federated Approvals card renders per-entry progress chips ("DevOps 1/2",
"Hussein Jarrar ✓").

## Migration (`a107c0nd1t10n`)

Data-rewrites `workflow_transitions.rules` (legacy checks → require_field
rows; flat approval params → entries — the old count only translates when the
rule was exactly ONE team, otherwise users approve personally and teams
default to 1) and converts in-flight `approval_requests` the same way before
dropping the three columns. Downgrade is lossy where the new model is richer
(value conditions drop; per-entry counts collapse to max).

## Editor (SPA)

`TransitionsSection` rebuilt: a CONDITION BUILDER — rows of
[field → operator → typed value control], fields grouped builtins/custom,
operators scoped per field, values via TokenMultiSelect (users, teams, labels,
issue types, cycles, releases, priorities, kinds, select options — display
names captured for the failure strings) or date/number inputs for bounds;
rows PATCH the moment they're valid, an operator waiting on values holds
locally with a "choose a value" hint. Approvers: entry rows (icon + name +
per-team "requires N member approval(s)" stepper + remove) and a SubjectPicker
"Add a person or team…" — the thousand-user checkbox grid is gone. The
enforcement select carries FRIENDLY labels ("Guarded — a matching rule's
conditions must pass") with the registry description beneath, and the
duplicate free-text `workflow_transition_mode` input on Project settings →
General is filtered out (it had a dedicated dropdown one page over).

Same pass, same anti-pattern (the last checkbox-pill grids over subject
lists): cycles "Visible to" teams and the internal-note "Visible to" toggles
became TokenMultiSelect.

Adjacent cleanup (same day): the INSTANCE Settings → General rendered the
enforcement mode as a raw free-text input (typing "gaurds" would have been
stored and blown up transition resolution). `SettingSpec` grew `choices` —
enumerated string settings 409 out-of-range writes server-side, the read
carries the accepted values, and the generic editor renders a friendly-label
SELECT (labels shared with the Workflow tab via `lib/meta`). The instance
value is the cascade DEFAULT every project inherits; the Workflow-tab
dropdown is the per-project override (Set here / Inherited).

Adjacent cleanup (same day): the Settings → Fields detail pane rendered a
215-pill unbounded wall for a big select field's options — with NO way to add
one (spec 100's additive-only `extend_options` had no endpoint or UI). Now:
`POST /fields/{id}/options` (field.update on the field's scope; dedupe is a
quiet no-op) + an options section with a count, a filter (>12 options), a
capped scrolling list, an "Add options" token input, and a hint explaining
why remove/rename deliberately don't exist (items already store the values).

## Follow-up (same day): applies-when scoping + first-match resolution

The rules were still project-global per edge — the user wants them scoped to
issue types / arbitrary item conditions. `workflow_transitions` gained
`applies_when` (migration `b107appl1es`): bare field-condition dicts (the
SAME shape/validator/evaluator as require_field params — one vocabulary,
one builder) scoping WHICH items a row governs; empty = every item.

**Resolution is FIRST-MATCH** (user-picked over stack-all): among the rows
for an edge — exact-from rows before wildcards, then list order — the first
row whose applies_when the ITEM satisfies governs the move ALONE. That is
strictly more expressive: a specific row above a general one can both stack
requirements ("Bugs: Site + approval" above "All: Site") and carve
EXEMPTIONS ("Bugs: no conditions" above "All: Site" frees bugs), at the cost
of repeating shared conditions. Consequences: the (project, from, to) dupe
409 is GONE (duplicate edges are legitimate, order resolves them — the
reorder arrows finally mean something); the snapshot builds BEFORE matching
(union of the candidates' applies_when + rules needs); strict mode
distinguishes 'no transition … is defined' (no row for the edge) from
'no transition … applies to this item' (rows exist, none matches the item).
The old `match_row` became three public pieces — `edge_candidates` (pure
ordering), `governing_row` (pure first-match), `snapshot_for` /
`governing_row_for` — and approvals resolves through them, so a rule scoped
to Bugs never offers "Request approval" on (or accepts a request for) a
non-Bug. Editor: the condition builder generalized over a bare list and
mounts TWICE per row — "Applies when" (empty text: "Every issue — add a
condition to scope this transition") above "Conditions" — with the
top-down/first-match rule explained in the section help.

## Tests / verification

`test_transitions.py` rewritten: the op matrix (presence specials keep legacy
strings, is/is_not incl. empty-passes-is_not and multi-valued overlap, date
phrasing, numeric comparison, boolean), write-validation (unknown field/op,
enum values, bad dates, missing values), approval entry validation + the
server-side name snapshot, and the guards/strict/wildcard integration flows on
the new shapes. `test_approvals.py` rewritten per-entry: team 2-of-3 with
auto-apply, two user entries AND-ing, mixed user+team, decline-terminal, live
team eligibility, banked unlocks. Follow-up adds: scoped row ignores
non-matching items, first-match exemption ordering, strict
"applies to this item", applies_when write-validation, duplicate edges
allowed, approvals requestable respecting scope. 1256 total. CDP proof against the dev
instance: the migrated `require_fields: [site]` rule renders as "Site — is
set", one checkbox on the whole page, approval toggle → entry row + picker →
team entry with stepper → restored clean.
