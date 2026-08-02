# Spec 38 — Item archive + delete (closing the oldest gap)

Items could never be removed; test junk and dead tickets lived forever. Two levels:

## Archive (soft, reversible, `item.update`)

- `work_items.archived_at` (nullable timestamp). **Archived items are excluded from
  every listing by default** (`apply_filters` adds the clause, so boards, saved
  views, SLQ results, and My Work all hide them); `GET /items?archived=true` lists
  archived ONLY. Detail stays reachable by key; SLA evaluation skips archived items.
- `PUT /items/{id}/archive` / `DELETE /items/{id}/archive` — an ordinary
  `item.updated` with an `archived` diff (History/notify/realtime for free).
- UI: Archive/Unarchive button on the issue header, an amber banner on archived
  detail views, an "Archived" toggle on the project List page.

## Delete (hard, admin, `project.manage`)

- `DELETE /items/{id}` → 204. **Children must be gone first** (the `parent_id` FK
  restricts; a clear 409 says so). Dependent rows CASCADE (comments, worklogs,
  estimates, links, stars, watchers, attachments rows, search index, SLA state).
- Emits `item.deleted` BEFORE the row goes (payload: key, title, project_id) —
  **the event log keeps the item's whole history**; the search indexer drops the
  index row on that event.
- UI: two-step Delete on the issue header (project admins), navigating home after.

## Known simplifications

- Attachment BYTES are orphaned on delete (rows cascade; storage GC later).
- No SLQ `archived` field yet (the structured `archived` param covers the UI; add
  the SLQ boolean when queries need to mix archived and active).
- Archived items remain in the search index (findable by key/title — arguably
  right; revisit if noise).
- Bulk archive isn't in the BulkActionBar yet.
