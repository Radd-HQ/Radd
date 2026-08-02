# Spec 68 — Bulk operations

Target-features wave, part 1. Multi-select on list/board surfaces plus two batch
endpoints: bulk-edit and bulk-move. Everything routes through the EXISTING items
service per item so RBAC, transition guards, events, automations, notify, search
and realtime all keep working with zero new semantics — the batch layer only adds
selection, iteration, and skip-and-report.

## 1. Backend — bulk update

- `POST /items/bulk-update` `{item_ids: [...], patch: {...}}` (authenticated).
  `patch` is a restricted subset of `ItemUpdate`: `state_id`, `assignee_id`,
  `team_id`, `priority`, `type_id`, `cycle_id`, `release_id`, `flagged`,
  `archived`, `add_labels: [...]`, `remove_labels: [...]` (labels are DELTAS in
  bulk — replacing the whole list is a single-item affordance). Explicit null
  clears (the `model_fields_set` idiom carries through).
- Cap: `len(item_ids) <= settings.bulk_max_items` (config, default 500) → 422.
- Per item: resolve, check `item.update` on its project, apply via
  `items.service.update_item` (per-item project-scoped values: a `state_id`/
  `type_id`/`release_id` that doesn't belong to the item's project → that item
  is SKIPPED, not 409 — bulk selections may span projects).
- SKIP-AND-REPORT, never fail the batch: response
  `{updated: [ids], skipped: [{item_id, key, reason}]}`. Reasons: `not_found`,
  `forbidden`, `invalid_target` (project-scoped value not applicable),
  `transition_blocked` (spec-61 guard failures — the TransitionError detail),
  `error` (anything else, logged). Each successful update emits the ordinary
  `item.updated` (with `changes`) — history/automations/notify unchanged.
- One transaction per ITEM (savepoint per item inside the request txn): a
  failing item rolls back only itself.

## 2. Backend — bulk move (cross-project)

- `POST /items/bulk-move` `{item_ids: [...], target_project_id}`. Actor needs
  `item.update` on each source project and `item.create` on the target
  (checked once). Same-workspace only (409 otherwise). Cap as above.
- Hierarchy: the epic/issue/subtask tree is same-project by invariant, so
  moving an item AUTO-INCLUDES all its descendants (dedup with the explicit
  selection; response lists them under `moved` too). A parent NOT being moved
  → the moved item's `parent_id` is cleared (reported per item as
  `parent_cleared: true`).
- Per-item mapping into the target project:
  - new key from the target's counter (`TD-42` → `DEV-97`); old key recorded.
  - state by NAME (case-insensitive) else the target's default state of the
    SAME CATEGORY else the target default; type by name else target default;
    `release_id` cleared (project-scoped); cycle kept (workspace-scoped);
    labels kept; custom fields: keys valid in the target scope kept, others
    dropped (reported as `dropped_fields: [...]`).
- **Key aliases:** new table `item_key_aliases` (`old_key` unique, `item_id` FK
  CASCADE, `created_at`). `items.find_item_by_key` falls back to the alias
  table, so `/issues/TD-42` keeps resolving after a move (router/SPA follow the
  item's CURRENT key in the response). Alias rows are also written for the
  auto-moved descendants.
- Emits `item.updated` per item with a `changes` diff covering `key` and
  `project` (display values) — every existing consumer (search reindex,
  history, realtime, webhooks) picks the move up without new event plumbing.
  Transition guards do NOT run (state mapping is a move artifact, not a user
  transition); spec-61 modes apply again from the next real state change.

## 3. Backend — ids for "select all matching"

- `GET /items/ids` — same filter surface as `GET /items` (structured params +
  `q` SLQ) but returns `{ids: [...], total}` with `ids` capped at
  `bulk_max_items` (and `total` the true count). Powers the "Select all N
  matching this filter" banner without paginating whole pages down.

## 4. Frontend (EXTEND the existing selection layer, don't rebuild)

- `routes/view.tsx` already owns `Set<id>` selection + shift-click range for
  LIST/PLANNING views and `components/views/BulkActionBar.tsx` fans per-item
  PATCHes out client-side. This spec upgrades that layer:
  - selection reaches BOARD cards too (checkbox overlay on hover/when a
    selection exists; plain click still opens the peek panel);
  - the bar's apply path switches from client fan-out to `POST
    /items/bulk-update` (one request, server-side skip-and-report; the
    result toast replaces per-item error toasts);
  - new bar actions: +Label/−Label, Flag, Archive, **Move to project…**;
    Type/Release pickers enabled only when the selection spans ONE project;
  - a "select page / select all N matching" header control backed by
    `GET /items/ids`.
- Result toast: "Updated 14 · Skipped 3 (2 blocked by transition rules, 1 no
  permission)" with a details popover listing skipped keys + reasons.
- Move flow: project picker modal → confirm ("keys will change; TD-… links
  keep redirecting") → toast with the new keys.

## 5. Tests (core invariants)

- bulk-update: permission-less item skipped w/ `forbidden`; guard-blocked item
  skipped w/ `transition_blocked` while the rest apply; cross-project
  `state_id` → `invalid_target`.
- bulk-move: re-key + alias resolution via `find_item_by_key`; descendant
  auto-move; state mapped by name; custom field dropped when absent in target
  scope; cycle preserved, release cleared.

## As-built notes

- Shipped as specced: `items/bulk.py` (bulk_update_items / bulk_move_items /
  list_item_ids), `item_key_aliases` (migration `f7392cb631ca`),
  `BulkSkipReason` enum, router endpoints `/items/bulk-update`, `/items/
  bulk-move`, `/items/ids`; alias fallback in both key resolvers.
- Bulk-update state/type/release pickers are PROJECT-scoped in the UI (ids
  can't span projects); priority/assignee/team/cycle/labels/flag/archive work
  cross-project. Transition guards run on bulk state changes (savepoint per
  item — a blocked item reports `transition_blocked` with the guard strings).
- Moves add a `parent_not_moved` skip reason (subtask selected without its
  parent) beyond the specced set. Guards deliberately DON'T run on the move's
  state mapping (documented in-spec).
- Frontend: the pre-68 client fan-out bar was replaced by a self-contained
  `BulkActionBar` (own option queries + server bulk calls + result toasts +
  move dialog); board cards got hover checkboxes; "Select all N matching"
  appears when the ad-hoc SLQ page filter is inactive (the id set must mean
  exactly what the fetch query means).
- Tests: `tests/test_bulk.py` (4) — skip-and-report incl. guard block +
  savepoint rollback, forbidden outsider, label deltas, move re-key/aliases/
  name-mapping/descendants, subtask-parent rule.

## Known simplifications

- Bulk label ops resolve through `labels.resolve_labels` (auto-create on first
  use) — consistent with automations.
- No undo; the per-item events are the audit trail.
- `/items/ids` runs the same visibility filtering as the list — the cap means
  "select all" on >500 matches selects the first 500 by the query's order (the
  banner says so).
