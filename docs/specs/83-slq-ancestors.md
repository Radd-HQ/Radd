# Spec 83 — SLQ ancestor fields (epic.* / parent.*)

User decision (discussion): epic membership STAYS `parent_id`
(single-parent tree, cycle-impossible ladder); SLQ gains ancestor traversal on
top — `epic.state = "In Progress" AND state = Done` — compiled as correlated
subqueries over the existing hierarchy. Filter-only (no ORDER BY) in this cut.

## 1. Semantics

- `epic` = the NEAREST EPIC ANCESTOR: an issue's parent (the ladder makes it
  an epic), a subtask's grandparent. Epics themselves have no epic →
  `epic IS EMPTY` is true for them (and for parentless issues).
- `parent` = the DIRECT parent, whatever its kind (epic for issues, issue for
  subtasks).
- Cross-project ancestors (spec 80) match naturally — the traversal is by id,
  not project.

## 2. Fields (both prefixes)

- `epic` / `parent` bare: `= KEY` / `!= KEY` (key resolved at compile time,
  alias-aware via the spec-68 resolver), `IS EMPTY` / `IS NOT EMPTY`.
- `epic.state` / `parent.state`: state NAME (case-insensitive, same
  resolution semantics as the item-level `state` field).
- `epic.category` / `parent.category`: StateCategory enum (validated like
  the item-level `category`).
- `epic.assignee` / `parent.assignee`: same value language as `assignee`
  (`me`, `none`, email/name resolution).
- `epic.priority` / `parent.priority`: Priority enum.

## 3. Compilation

- One aliased self-join chain per queried prefix: P (parent row), G
  (grandparent). `parent.*` conditions target P; `epic.*` target the CASE
  nearest-epic id (P when P.kind='epic', else G when G.kind='epic') via a
  correlated EXISTS/scalar subquery — the compiler builds it once per query
  and ANDs conditions into it (multiple `epic.*` terms share the join).
- Registered in the SLQ catalog + suggest (field names complete; value
  suggestions reuse the item-level sources for state/category/assignee/
  priority; `epic`/`parent` values suggest item keys like the link surfaces).

## 4. Tests

- issue-under-epic matches `epic.state`; subtask matches via grandparent;
  epic itself and parentless issue are `epic IS EMPTY`; `parent.*` targets
  the DIRECT parent for subtasks (issue, not epic); cross-project ancestor
  matches; bad enum values 422 with position; `epic = KEY` incl. an aliased
  (moved) key.

## Known simplifications

- Filter-only: `ORDER BY epic.state` is rejected like other unsupported
  sorts.
- Ancestor label/custom-field paths are out of scope for this cut.

## As-built notes

Shipped as specified; everything lives in `server/src/radd/modules/items/slq/`.

- **New module `ancestors.py`** carries all ten compilers (bare `epic`/`parent`
  + the eight dotted sub-fields) plus the compile-time key machinery;
  `compiler.py` merges `ANCESTOR_COMPILERS` over `BUILTIN_COMPILERS` into one
  dispatch table (bare `parent` moved out of `builtins.py`).
- **Fields are ordinary `SlqField` members** (`epic`, `epic.state`, …,
  `parent.priority` — the lexer already word-lexes dots, so no lexer/parser
  changes). That one registration gives catalog op-tables, ORDER BY rejection
  (none are sortable → the standard "is not sortable" 422), did-you-mean
  candidates, and suggest field completion for free.
- **Nearest-epic compilation:** one aliased P (parent) / G (grandparent)
  self-join chain per condition, correlated on the outer row, selecting
  `CASE WHEN P.kind='epic' THEN P.id WHEN G.kind='epic' THEN G.id END` as a
  scalar subquery (NULL for epics and parentless items → `epic IS EMPTY`
  covers both). Sub-field conditions compile to `<ancestor id> IN (SELECT id
  FROM work_items WHERE <predicate>)` — correlated comparisons, never joins,
  so OR/NOT stay correct and `!=`/`NOT IN` follow the usual SQL NULL rule
  (items without the ancestor don't match). `parent.*` tests
  `WorkItem.parent_id` directly. Per-condition subqueries (not one shared
  per-query join) match the compiler's pure node-by-node dispatch; the chain
  builder is shared code.
- **Key resolution** is a `compile_query` pre-pass mirroring label
  resolution: `ancestor_key_texts` walks the AST for well-formed bare
  epic/parent keys, `resolve_ancestor_keys` maps them through the spec-68
  alias-aware `find_item_by_key` (lazy import — the items service imports
  this package) into `Context.ancestor_ids_by_key`; a miss raises a
  positioned `unknown item 'X'` SlqError. BEHAVIOR CHANGE: `parent = KEY`
  with a nonexistent key was a silent empty match, now a 422 (and aliases of
  moved items now resolve). The three `parent = <key>` cases in
  `test_slq.py`'s pure (session=None) compile list moved to the new
  DB-backed suite accordingly.
- **Value semantics:** state names match case-insensitively
  (`lower(State.name)`) as specified — the item-level `state` field stays
  exact-match; category/priority validate through the shared `enum_values`
  (positioned 422, e.g. `invalid epic.category 'nope'`); assignee reuses a
  new shared `builtins.user_match` helper (`me`/`none`/email — `_assignee`/
  `_reporter` were refactored onto it; no display-name matching, exactly
  like the item-level field).
- **Suggest:** field names complete (all nine); values reuse the item-level
  sources — states, categories, `me`/`none` + users, priorities; bare
  `epic`/`parent` offer `none` + item keys via the existing
  `_item_key_candidates`. New DB-backed fields added to `_DB_BACKED_FIELDS`.
- **Tests:** `tests/test_slq_ancestors.py` (18) — parent/grandparent
  traversal, IS EMPTY for epics/parentless, direct-parent targeting,
  cross-project + alias matching after a bulk move, positioned 422s
  (bad enum, unknown/malformed key), ORDER BY rejection for all nine
  fields, suggest field/value coverage. One ranking expectation in
  `test_slq_suggest.py` updated (the partial "te" now also
  contains-matches `epic.state`/`epic.category`/`parent.state`/
  `parent.category`). Suite: 796 green.
- **Sync surfaces updated:** `web/src/lib/slq.ts` cheat sheet (one `epic`
  row) and the NL→SLQ prompt field list in `radd/modules/ai/prompts.py`.

## Amendment — `epic` is REFLEXIVE

§1's "epics themselves have no epic" was wrong, and spec 98 had already
contradicted it: the timesheet's grouping seam (`items.service.epics_for_items`)
maps an epic to ITSELF, because time logged straight onto an epic belongs under
it. SLQ kept the strict-ancestor reading, so an epic's `epic` id was NULL and it
matched NO `epic.*` condition at all — not even negated ones, since
`NOT (NULL IN (…))` is NULL. `epic.category != done` returned the children of
unfinished epics and silently dropped the epics.

**`epic` names a CONTAINER, and an epic belongs to itself.** `parent` is
unchanged — it is genuinely relative, and an item is never its own parent.

- One shared definition, `items/hierarchy.py::nearest_epic_case(item, parent,
  grandparent)`: self arm, then parent, then grandparent. Both consumers build
  it and differ only in binding — `service/queries.py` joins the chain for a
  batch, `slq/ancestors.py` correlates it per outer row. That file is also
  where the rule is written down, so the two can't drift again.
- `slq/ancestors.py::_epic_id` now correlates on the ITEM (`item.id ==
  WorkItem.id`) and outer-joins upward, instead of correlating on the parent —
  a parentless epic produced no subquery row at all before, so the self arm
  could not be reached from inside. Costs one PK self-lookup per correlated
  evaluation; the per-condition-subquery simplification above is untouched.
- Epic nesting can't muddy this: `REQUIRED_PARENT_KIND` gives epics no parent
  kind, so `_resolve_parent` 409s any parent on an epic. Every item has at most
  ONE epic in scope, and the rule stays well-defined (self, then walk up) if
  the ladder ever grows.
- **Behaviour change:** `epic IS EMPTY` / `epic = none` no longer match epics —
  they now mean "work no epic governs" (a parentless issue and its subtasks),
  the exact complement of `IS NOT EMPTY`. `kind = epic` asks the old question.
  `epic = KEY` returns the epic plus its tree; `epic != KEY` returns the other
  epics plus theirs.
- Delegation inherits it: the worklog dialect's `issue.epic = KEY` now selects
  the same hours the timesheet files under that epic, worklogs on the epic
  itself included (`test_worklog_slq.py`).
- Tests: `test_slq_ancestors.py` reflexive expectations + the motivating
  `epic.category != done` case; `test_worklog_slq.py` asserts the delegated
  filter and `epics_for_items` agree. Suite: 991 green.
