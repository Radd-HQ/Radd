# Spec 55 — Page-level SLQ bars: validate-on-type / run-on-Enter + pagination

**Status: shipped** (rounds 14–15 of the polish thread).

## Problem

Round 14 put an ad-hoc SLQ bar on every content page (board, list, cycle,
planning, roadmap, saved views). The original list-bar design executed the
query on every settled keystroke — fine for a demo project, hostile at scale:
every valid intermediate draft (`priority = high` on the way to
`priority = high AND label = x`) ran a real query over the items table, and
unindexable operators (`~` ILIKE, JSONB custom fields, OR-heavy) scan. Item
surfaces also silently capped at one 200-item page.

## Design

**Typing validates, Enter executes.**

- `GET /items/slq/validate?q=[&project_id=]` (`items/service.validate_slq`) —
  parse + compile with field/label resolution (cheap registry lookups), ZERO
  work_items I/O. Blank = trivially valid; invalid → the standard 422
  `{detail, position}` incl. did-you-mean. Gated `item.read` like suggest.
- Frontend `useSlqValidation` (hooks.ts) replaced the live-execute
  `useSlqProbe` at EVERY probe surface — page bars, ViewModal, quick-filter
  chip rows, automation RuleEditor. No surface executes SLQ speculatively.
- `useSlqPageFilter` (lib/slq-filter.ts) holds a `committed` query set by
  `run()` (Enter) / `runQuery()` (NL→SLQ auto-runs). Status line gained
  `ready` ("Valid — press Enter to run"); match counts appear only after a
  run. Suggest (autocomplete) stays per-keystroke — bounded value lookups.
- Editor Enter semantics (the Jira rule): with the dropdown open, Enter
  accepts a suggestion ONLY after arrow/hover navigation (`navigatedRef`);
  otherwise it runs the query. Tab always accepts. Esc cancels even a
  still-debouncing suggest request (was a reopen-after-Esc race).

**Pagination everywhere** (offset-based, pages of `ITEMS_PAGE_LIMIT`):

- Board + roadmap → `infiniteItemsQuery` (Load more footer / header link).
- Saved views → `infiniteViewItemsQuery` (same `viewItems` cache key, now
  `InfiniteData`; Load more strip; CSV exports the loaded+filtered set).
- Planning sections → paged per section (backlog Load more).
- Committed list-bar results → `infiniteSlqItemsQuery` (DISTINCT cache key
  from the flat `slqItemsQuery` — same key + different shapes would corrupt).
- `item-mutations.ts`: `mapPages`/`transformPages` helpers; move/update/
  star/reorder patch the paged shapes optimistically (reorder = flatten →
  splice → re-chunk by page lengths).

## Semantics

List swaps its base set to the committed server result (honors ORDER BY).
All other pages intersect their own content with the match set by id, so
layout/grouping/order stay put. The intersection match set is one page at the
API cap — the status line's "N+" flags it.
