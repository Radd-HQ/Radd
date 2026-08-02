# Spec 43 — Wiki: doc spaces, page trees, versions, issue↔doc links

The Confluence half of the mission (PLAN §8 remaining #1). A new **`docs`
module** (`radd.modules.docs`) + full frontend. Content is **markdown**,
edited with the existing safe `MarkdownEditor` (same body pipeline as item
descriptions — mentions, paste-to-attach deferred for pages). Real-time
co-editing (Yjs/pycrdt) is **deferred**: the box has no JS package manager to
vendor a Yjs client, so this ships the PLAN §9 fallback — single editor +
optimistic-concurrency guard + full version history. The CRDT can land later
behind the same PATCH contract.

## Data model (one migration; head off the current single head)

- `doc_spaces` — id uuid PK, workspace_id FK, name, slug (unique per
  workspace), description text default '', position float, created_at.
- `doc_pages` — id uuid PK, space_id FK CASCADE, parent_id self-FK nullable
  (page tree), title, body text default '' (markdown), position float
  (sibling order), version int default 1, created_by FK users, updated_by FK
  users, created_at, updated_at, archived_at nullable. Index (space_id,
  parent_id).
- `doc_page_versions` — id uuid PK, page_id FK CASCADE, version int, title,
  body, author_id FK users, created_at. Unique (page_id, version). A row is
  written for the PREVIOUS content on every content-changing update (so
  version N's row exists once version N+1 is current).
- `item_doc_links` — item_id FK CASCADE, page_id FK CASCADE, created_by,
  created_at; PK (item_id, page_id).

## Permissions (auth/types.py — same pattern as spec 36)

- `DOC_READ = "doc.read"` (workspace scope) → added to the builtin VIEWER
  role's code permission set (flows into `WORKSPACE_MEMBER_FLOOR`).
- `DOC_WRITE = "doc.write"` (workspace scope) → builtin MEMBER role set +
  `WORKSPACE_MEMBER_SCOPE` (members write docs; a read-only-for-members wiki
  is useless).
- `DOC_MANAGE = "doc.manage"` (workspace scope, admins only): create/rename/
  delete SPACES, hard-delete pages, restore archived pages.
- `tests/test_authz.py` pins exact floor sets — update the pinned assertions
  (same as specs 22/36 did).

## API (all under the module router)

- Spaces: `GET/POST /doc-spaces?workspace_id=` (read=doc.read,
  write=doc.manage), `PATCH/DELETE /doc-spaces/{id}` (doc.manage; DELETE 409
  unless empty or `?force=true` which cascades).
- Pages: `GET /doc-spaces/{id}/pages` → flat list (id, parent_id, title,
  position, has_children, updated_at) — the client builds the tree;
  `POST /doc-pages {space_id, parent_id?, title, body?}` (doc.write);
  `GET /doc-pages/{id}` (doc.read; full body + space + breadcrumb trail);
  `PATCH /doc-pages/{id} {title?, body?, parent_id?, position?, expected_version?}`
  (doc.write) — **optimistic concurrency**: when `expected_version` is sent
  and ≠ current version → 409 with the current version in detail (the editor
  warns instead of clobbering); content changes bump `version` and snapshot
  the previous content into `doc_page_versions`; parent moves reject cycles
  (409 "would create a cycle" — walk ancestors).
  `DELETE /doc-pages/{id}` (doc.write) archives (`archived_at`); hard delete
  = doc.manage + `?hard=true`, 409 if it has non-archived children.
- Versions: `GET /doc-pages/{id}/versions` (meta list),
  `GET /doc-pages/{id}/versions/{n}` (full body),
  `POST /doc-pages/{id}/restore {version}` (doc.write — restore = a NEW
  version whose content is the old one).
- Links: `POST /doc-pages/{id}/items {item_key}` + `DELETE .../items/{item_id}`
  (doc.write + item.read on the item; resolve via `items.find_item_by_key`),
  `GET /doc-pages/{id}/items` (linked items w/ key/title/state),
  `GET /items/{id}/docs` (pages linked to an item — lives in the docs module,
  path-extends the items surface like timelogging does).
- Search: `GET /docs/search?q=&workspace_id=` (doc.read) — Postgres FTS over
  title+body via an expression GIN index built in the migration
  (`to_tsvector('english', title || ' ' || body)`), ranked, headline snippet.
  No outbox indexer — the corpus is written through this module only, so
  querying live is simpler and always fresh.

## Events (audit + realtime + automations for free)

`doc_space.created/.updated/.deleted`, `doc_page.created/.updated/.deleted/
.moved/.restored`, `doc_link.created/.deleted` — entity_type `doc_space`/
`doc_page`, workspace_id set, payloads carry names/titles + (for updates) a
changed-fields list. Realtime: add the entity strings to the frontend
`SERVER_ENTITY_TAGS` map → live tree/page updates.

## Frontend

- Sidebar: a **Docs** section (spaces list; ⚙ → `/settings/docs` when
  doc.manage) between Views and Cycles.
- `/docs` — spaces index (name, description, page count). `/docs/$spaceId` —
  two-pane: collapsible page TREE (client-built, expand/collapse persisted
  per space in localStorage, "+ page" at root and per node when doc.write)
  and the selected page. `/docs/$spaceId/$pageId` — canonical page URL.
- Page view: title (inline-editable), rendered markdown body, byline
  (updated_by + relative time + "v{n}"), **Edit** → the existing
  `MarkdownEditor` with Save/Cancel; Save sends `expected_version` and on 409
  shows "changed since you opened it — reload or overwrite". History tab
  (versions list → view a version → Restore). **Linked issues** panel:
  linked items (key chip + title + state) + add-by-key input; the ISSUE page
  gets a matching **Docs** row in its Related links area (`GET
  /items/{id}/docs`, link + unlink).
- Cmd-K palette: doc results merged in (a second query to `/docs/search`,
  section-headed "Docs").
- Cache: new `Entity.docSpace`/`docPage` tags; queries tagged, mutations
  invalidate by entity (the repo convention).

## Tests (pure core only, repo style)

Tree/cycle-guard helper (pure), version-snapshot decision (pure function
deciding when to snapshot/bump), FTS query builder if hand-built. Everything
else: in-process ASGI verification + live run.

## Known simplifications

- No real-time co-editing yet (single editor + optimistic 409 + versions;
  pycrdt lands behind the same PATCH seam later — client lib blocked on the
  no-npm box).
- No per-space ACLs (workspace-wide read/write; the RBAC seam can grow
  space grants later the way fields grew grants).
- No page-level attachments/mentions yet (body is plain markdown; the item
  editor's attachment flow is item-bound).
- Slugs are cosmetic (URLs use ids); no Confluence importer yet (§8 gap).
