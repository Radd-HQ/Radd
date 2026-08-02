# Spec 28 — Search + Cmd-K command palette

Tier-1 item 3 from `docs/roadmap-ideas.md`: at ~122 issues/week you need instant
jump-to-key, full-text search, and fast navigation. Backend = Postgres FTS maintained
by an outbox consumer; frontend = a Cmd-K palette that quick-opens issues, navigates,
and (later) runs actions. pgvector/semantic search arrives with the `ai` module.

## Module: `radd/modules/search/`

### Index table `search_index` (one row per item)

`item_id` PK (FK work_items CASCADE) · `project_id` · `workspace_id` · `key` ("TD-123")
· `title` · `description` · `comments_text` (PUBLIC comment bodies, newline-joined) ·
`tsv` TSVECTOR (GIN-indexed) · `updated_at`. The `tsv` is recomputed in SQL on every
upsert: weight A = key (both `TD-123` and `TD 123` token forms) + title, B =
description, C = comments. Config `SEARCH_TS_CONFIG = "english"`.

### Indexer (outbox consumer, cursor `search.indexer`)

Mirrors the notify/webhooks dispatcher loop. `item.created`/`item.updated` → upsert
key/title/description; `comment.created/.updated/.deleted` → re-aggregate the item's
public comment bodies (via a new comments seam `public_bodies_for_item`). Upserts are
idempotent, so the **first run replays the whole backlog from offset 0 and that IS the
index build** — no separate bootstrap path (unlike notify, replay is exactly what we
want). Deleting the row follows item DELETE when that lands.

### `GET /search?q=&workspace_id=&limit=`

Two match strategies, merged (key hits first, dedup, newest-first tiebreak):

1. **Key prefix** — `q` shaped like a key or key fragment (`TD`, `TD-1`) → `key ILIKE q%`.
2. **Full text** — `q` → a prefix tsquery (`render & farm:*` — last term gets `:*` so
   type-ahead matches mid-word), ranked by `ts_rank_cd`, with a `ts_headline` snippet
   over description+comments.

RBAC: results filtered to projects where the caller holds `item.read`
(`authz.permissions_for_projects` over the instance's projects, one batched pass).
Response rows: `{item_id, key, title, project_id, snippet}`.

The tsquery builder is pure (`build_tsquery` in `service.py` — strips tsquery
metacharacters, tokenizes, ANDs, prefix-stars the last term), tested in
`tests/test_search.py`.

## Frontend — Cmd-K command palette

`components/CommandPalette.tsx`, mounted once in `AppLayout`:

- **Cmd/Ctrl-K** (or the sidebar Search row) opens a centered overlay input.
- Results, keyboard-navigable (↑/↓/Enter/Esc):
  - **Issues** — debounced `GET /search?q=` (top 8): key badge, title, snippet;
    Enter/click navigates to `/issues/$key`.
  - **Go to** — client-side filtered navigation: static destinations (Projects,
    Inbox, Timesheet, Reports, Settings…) + per-project Board/List/Roadmap/Reports.
- Empty query shows the navigation list; typing interleaves issue results above it.

## Known simplifications

- Internal comment bodies are NOT indexed (searchable text would leak to holders of
  plain `item.read`); public comments only.
- The index stores one row per item instance-wide; `workspace_id` narrows when passed.
- No fuzzy/typo tolerance (FTS prefix match only) and no people search endpoint —
  the palette lists users client-side later if needed.
- Palette actions (assign, set state) deferred — navigation + quick-open first.
- Comment edits re-aggregate ALL public bodies per event (fine at studio scale).
