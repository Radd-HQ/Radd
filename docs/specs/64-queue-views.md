# Spec 64 — Queue views

Service-desk wave, part 4 — the queue skin spec 30 deferred. A queue is a saved
view rendered for triage work: always-on SLA urgency, reporter visible, oldest
first, live counts in the sidebar. Queues reuse the ENTIRE view machinery
(SLQ membership, sharing, quick filters) — this is a view TYPE, not a module.

## 1. ViewType.QUEUE (views module)

- New `ViewType.QUEUE` value; accepted everywhere a view_type is validated.
  `group_by`/`swimlane_by` are ignored for queues (stored but unused, like
  planning). No migration (view_type is a string column).

## 2. Counts (views module)

- `POST /views/counts` body `{view_ids: [≤50]}` → `{view_id: count}` — a
  compiled-SLQ `SELECT count(*)` per view, visibility-filtered exactly like
  the view read path (invisible ids simply omitted). One batched call powers
  the sidebar badges; no per-view N+1.

## Frontend

- New-view modal offers **Queue** (icon: inbox/list-ordered) alongside
  board/list/planning.
- Sidebar gains a **Queues** collapsible section (existing spec-60 section
  idiom) listing the queue views visible to the actor with count badges
  (batched counts query, 60s refetch).
- The view page renders queues as a list variant: reporter column, age column
  (created_at → "3d"), SLA chip column ALWAYS on (spec 63 batch endpoint),
  and default ordering by SLA urgency — breached first, then ascending
  due_at, then created_at asc — computed client-side over the loaded page
  when the view's SLQ has no explicit ORDER BY. Quick filters + the SLQ bar
  work unchanged.

## Tests

Count endpoint (visibility filtering + compiled query correctness) and
queue-type acceptance folded into the existing views test module.

## Known simplifications

- Urgency ordering is client-side over the loaded page (server-side SLA
  ordering needs due-time indexing — spec 30's known deferral stands).
- No per-queue column config in v1 (the queue column set is fixed).

## As-built notes

- No migration: `view_type` is a plain `String(20)` column — `queue` just
  fits; alembic head stays `fb577d3807f9`.
- Counts live in `views/counts.py` (service.py was already ~635 lines —
  file-size rule). Semantics beyond the spec text:
  - The `list_views` membership gate applies per view (item.read at the
    view's workspace) — a non-member's ids are omitted like invisible ones.
  - Items are counted the way the read path would RENDER them: archived
    excluded (spec 38 default) and only projects where the actor holds
    item.read count; a visible view over an unreadable project counts 0.
    Workspace-spanning views count within the view's workspace (the spec's
    scope wording), not the cross-workspace `GET /items` superset.
  - A stored query that no longer compiles (registry drift, e.g. a deleted
    custom field) omits THAT view from the response instead of 422-ing the
    whole batch.
- Frontend:
  - Queue views render ONLY in the sidebar's Queues section (with badges);
    they're excluded from the generic workspace/project view lists so a
    queue never appears twice. The section folds under the spec-60 prefs id
    `queues` and hides when no queue views are visible.
  - Fixed columns = `DEFAULT_QUEUE_SLOTS` (type/labels/priority/assignee/
    state) + a queue-only reporter/age/SLA cluster (`QueueRowMeta`); the
    DisplayMenu is hidden on queues (fixed column set per the spec).
  - Ordering key (lib/queue.ts): OPEN breaches first (met timers are
    settled and ignored), then min open `due_at`, then `created_at` asc;
    items without timers sort after dued ones. An explicit ORDER BY in the
    view's SLQ keeps the server order untouched.
  - Manual drag-to-rank is disabled on queues (the urgency sort would fight
    it); multi-select + bulk actions, quick filters, the SLQ bar and Load
    more work unchanged.
  - Icon: lucide `list-ordered` (modal option, view header, sidebar rows).
