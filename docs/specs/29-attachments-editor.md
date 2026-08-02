# Spec 29 — Attachments + rich(er) text editor

Tier-1 item 4 from `docs/roadmap-ideas.md`: artist support needs pasted screenshots,
frames, and logs; descriptions/comments were plain `<textarea>`s. The roadmap's
planned editor stack is Tiptap, but this box has **no JS package manager** (no
npm/pnpm/bun), so this spec ships the dependency-free 90%: **markdown content with a
safe hand-rolled renderer, paste-to-upload attachments, and @mention autocomplete**.
Content is stored as markdown text (the same `description`/comment `body` columns), so
a later Tiptap upgrade is a pure frontend swap over identical data.

## Backend: `radd/modules/attachments/`

- `attachments` table: id PK, `item_id` FK work_items CASCADE (attachments belong to
  an ITEM; images pasted into comments upload to the item and embed by URL), original
  `filename`, `content_type`, `size_bytes`, `storage_name` (uuid on disk), `created_by`,
  created_at.
- **Storage: local filesystem** — `RADD_ATTACHMENTS_DIR` (default `var/attachments`
  under the server cwd), flat uuid-named files. S3-compatible object storage is a
  later `storage` seam when multi-node matters.
- API:
  - `POST /items/{id}/attachments` (multipart, `item.update`) → streams to disk with a
    `RADD_ATTACHMENT_MAX_BYTES` cap (default 25 MB, over → 413); returns the row.
  - `GET /attachments/{id}` (`item.read` on the item's project) → the bytes,
    `X-Content-Type-Options: nosniff`; `inline` disposition for `image/*`,
    `attachment` (download) for everything else so hostile HTML/SVG never renders
    in-origin. `image/svg+xml` is treated as non-image (downloads).
  - `GET /items/{id}/attachments` (`item.read`) · `DELETE /attachments/{id}`
    (uploader or `project.manage`) — removes row + file.
- Events `attachment.created/.deleted` (payload item_id, filename, size_bytes) →
  added to items' `RELATED_EVENT_TYPES` so they appear in the History feed.

## Frontend

- **`lib/markdown.tsx`** — a small markdown-subset renderer that emits **React
  elements only (no innerHTML anywhere → XSS-impossible by construction)**:
  paragraphs, `#`–`###` headings, `**bold**`, `*italic*`, `` `code` ``, ``` fences,
  `>` quotes, `-`/`1.` lists, `- [ ]` checklists, `[text](url)` links (http/https/
  same-origin only), `![alt](url)` images (same restriction), and `@[Name](uuid)`
  mention chips. Unknown/raw HTML renders as literal text.
- **`components/items/MarkdownEditor.tsx`** — textarea with Write/Preview tabs:
  - **Paste or drop an image/file** → uploads to the item → inserts
    `![name](/api/v1/attachments/{id})` (or a link for non-images) at the cursor.
  - **`@` mention autocomplete** (workspace users, ↑/↓/Enter) inserting
    `@[Name](uuid)` — the exact token the notify consumer parses (spec 26).
- **Issue description**: rendered markdown, click (or Edit) to open the editor with
  Save/Cancel. **Comments**: bodies render as markdown; the composer is the editor.
- **Attachments section** on the issue (under Description): thumbnail grid for
  images, file chips otherwise, upload button + the editor's paste path, delete ×.
- New-item modal keeps its plain textarea (markdown is still stored verbatim).

## Known simplifications

- Editor is markdown-source (Write/Preview), not WYSIWYG — Tiptap lands when the
  toolchain allows installing it; stored content needs no migration.
- Attachments always parent to an item (comment-pasted images included); no orphan
  GC for images whose markdown reference is later deleted.
- Local-disk storage only; back up `RADD_ATTACHMENTS_DIR` alongside Postgres.
- No thumbnail generation (browser scales full images in the grid).
- New-item modal description stays a plain textarea (no item to attach to yet).
