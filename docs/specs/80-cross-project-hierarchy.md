# Spec 80 — Cross-project hierarchy & links

User direction: "I want to make a TD ticket a child of a DEV ticket and vice
versa — I do not want this limitation." The same-PROJECT invariant on manual
links and parenting is lifted; the WORKSPACE stays the hard boundary (as it is
for cycles, labels, teams). The kind ladder (epic ← issue ← subtask, depth 3)
is unchanged — it's semantics, not scoping.

## 1. Parenting (items module)

- `_resolve_parent` drops the same-project check; the parent must exist, be in
  the SAME WORKSPACE (409 otherwise), and satisfy the kind ladder exactly as
  today. Applies to create + update.
- Hydration/child_count/history are id-based — untouched. Epic rollup already
  walks parent_id project-agnostically (readable filter stays on requested
  roots; aggregate counts over cross-project children are numbers, not data —
  documented).

## 2. Links (items module)

- `_check_link_rules` replaces "same project" with "same WORKSPACE" (409) for
  the manual types (blocks/relates/duplicates). Mentions were already
  cross-project. Self-link/dup/symmetric rules unchanged.
- `GET /items/link-search` keeps its signature but searches the anchor
  project's whole WORKSPACE (visibility-filtered per project), ranking
  same-project matches first — the dependency add-row and the roadmap's
  cross-project link drags both just start working.

## 3. Bulk move consequences (spec-68 revision)

Auto-including descendants existed BECAUSE the hierarchy was same-project.
With that lifted, the honest semantics are: **a move moves exactly the
selected items** — children keep their parents across projects (now legal) and
stay where they are unless also selected.

- `_expand_descendants` auto-include: REMOVED. `parent_cleared` and the
  `PARENT_NOT_MOVED` skip reason: REMOVED (nothing needs clearing/skipping).
- Move-dialog copy updates: "items keep their parent/child links; select
  sub-items too if they should move along."

## 4. UI touchpoints

- Parent picker (issue view) + dependency add-row typeahead: workspace-wide
  candidates, same-project ranked first (falls out of §2's link-search; the
  parent picker uses whatever source it uses today — widen it the same way).
- Roadmap: cross-project link creation stops 409ing; project-scoped roadmap
  views simply won't LOAD other projects' children (their bars appear on
  workspace-spanning roadmaps — documented).

## 5. Tests

- parenting: cross-project parent accepted; cross-WORKSPACE parent 409; kind
  ladder still enforced.
- links: cross-project blocks accepted; cross-workspace 409; link-search
  returns cross-project candidates ranked after same-project.
- bulk-move: subtask moves ALONE keeping its parent; an epic move leaves
  children behind; update the spec-68 tests accordingly.

## Known simplifications

- Epic rollup counts descendants the actor may not read (aggregates only).
- Project-scoped surfaces (boards/lists) show cross-project children only via
  workspace-spanning views — by design, views are the cross-project surface.

## As-built notes

Validation-only — NO schema change, no migration.

**Parenting** (`items/service.py`): `_resolve_parent` now takes the child's
`workspace_id` (was `project_id`); the parent must exist, live in the same
WORKSPACE (409 "belongs to another workspace" — one `get_project` on the
parent resolves it), and satisfy the unchanged kind ladder. Both call sites
(create_item, update_item) pass `project.workspace_id`. Parent hydration was
already cross-project-safe (`_parents_by_id` folds parents' project ids into
the keys lookup), as was link hydration (mentions crossed projects before).

**Links**: `_check_link_rules` compares workspaces (two `get_project` calls,
only on the cross-project path); self/dup/symmetric rules untouched.
`_resolve_link_target` unchanged in behavior — `target_number` still means
"the SOURCE item's project" (the bare-number form), `target_id` reaches across.
`link_search` keeps its signature but candidates come from the anchor
project's workspace filtered to readable projects
(`authz.permissions_for_projects` over `list_projects(workspace_id)`), with
two-tier SQL ordering (`(project_id == anchor).desc(), number.desc()`) and
per-item project keys from `project_keys`.

**Bulk move revision** (`items/bulk.py`): `_expand_descendants` replaced by
`_selected_items` (plain dedup fetch in selection order); `_move_one` lost the
`moved_ids` param and the parent-clearing block — `parent_id` is simply kept;
`parent_cleared` dropped from `BulkMovedItem`, `PARENT_NOT_MOVED` dropped from
`BulkSkipReason` (server enum + web const-object + BulkActionBar reason
label); the move-dialog copy now says items keep their parent/child links and
sub-items must be selected to move along.

**Web**: the parent picker turned out to be NewItemModal's static
`<SelectField>` over `itemsQuery(project.id)` (create-time only — no
set-parent affordance exists on the issue view). It's now a debounced
typeahead over `linkSearchQuery` (limit `PARENT_SEARCH_LIMIT = 25`, the
router cap; query key gained the limit) with the kind ladder filtered
client-side (`requiredParentKind`) and a picked-parent chip with clear.
`DependenciesSection`'s add-row keeps the typed number/key form as
`target_number` but PICKED suggestions now submit `target_id` — a candidate
from another project would otherwise mis-resolve by number.

**Tests**: `tests/test_cross_project.py` (5 — cross-project parent on create
AND update, cross-workspace parent 409, ladder 409 across projects,
cross-project blocks link + cross-workspace 409, link-search two-tier ranking
with per-project keys); `tests/test_bulk.py` move tests revised (children
stay + keep parents unless selected; subtask moves alone keeping its parent;
re-key/alias/state-mapping/field-drop assertions kept). Suite 781 green.

**Deviations**: none from the spec text. Typed cross-project KEYS in the
add-link input (e.g. "DEV-23" while on TD) still resolve as a same-project
number — documented in modules.md; the typeahead is the cross-project path.
