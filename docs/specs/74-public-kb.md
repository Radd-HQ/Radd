# Spec 74 — Public knowledge base

> **Superseded by spec 121 §5 (RADD-1147).** The parallel model
> this spec built — `page_spaces.public` as the credential, its own
> `/public/pages` router with trimmed schemas, a separate `/public-pages` SPA,
> a `public_only` search path and an embed-time public flag — is gone. A public
> space is now the **Public** role granted to the **Anyone** principal on the
> space (`PUT /page-spaces/{id}/public-access`), read through the ordinary page
> routes by the ordinary space-scoped resolvers, inside the ordinary shell, with
> attachments downloading through the ordinary chokepoint (the "broken images"
> simplification below is fixed by construction). Kept as the historical record.

Target-features wave, part 7. Opt-in PUBLIC wiki spaces readable without login
(read-only, no edit affordances), plus KB deflection on the PUBLIC form page —
deflection matters most exactly where the visitor has no account.

## 1. Space flag (docs module)

- `doc_spaces.public` BOOL NOT NULL default false. Toggled via the existing
  space PATCH (`doc.manage`); `DocSpaceRead.public`. Archived pages never
  leak (public reads filter `archived_at IS NULL`).

## 2. Public read API (docs `public_router`, forms-style)

- New `APIRouter(prefix="/public/kb")`, NO CurrentUser anywhere:
  - `GET /public/kb/spaces` → public spaces `[{id, name, slug, description}]`.
  - `GET /public/kb/spaces/{id}/tree` → the page tree (id, title, parent_id,
    position; non-archived) — 404 for non-public spaces.
  - `GET /public/kb/pages/{id}` → `{id, space_id, title, body, breadcrumb,
    updated_at}` — 404 unless its space is public. Markdown body rendered
    CLIENT-side by the existing safe renderer.
  - `GET /public/kb/search?q=[&space_id=]` → live-FTS over PUBLIC spaces only
    (reuses `docs.search.search_pages` with a public-space filter — the
    tsvector expression is shared).
- No versions/history/links exposure — page bodies only.

## 3. Public form deflection

- `GET /public/forms/{token}/deflect?q=` (public router, token-gated like the
  form itself): top-5 public-KB pages via §2 search. ITEMS ARE NOT SEARCHED —
  resolved issues stay internal; only public docs deflect anonymous visitors.
- The public form page mounts the existing `DeflectionPanel` UI against this
  endpoint (links open the public KB routes).

## 4. Frontend (routes OUTSIDE the auth gate)

- New public routes: `/kb` (space cards), `/kb/$spaceId` (tree + first page),
  `/kb/$spaceId/$pageId` (tree rail + rendered page — a read-only sibling of
  `DocSpacePage` composing the same `PageTree`/render components with public
  queries local to the route files, minimal chrome + Radd mark header, and a
  "Sign in" link).
- Space settings (`/settings/docs` + space header): a "Public" toggle with a
  copy-link affordance to `/kb/{id}`.
- Authed docs pages show a small "Public" badge on public spaces.

## 5. Tests

- public endpoints: non-public space 404s (tree, page, search scope); archived
  page invisible; search hits public pages only.
- toggling `public` off immediately 404s the routes (no caching layer).

## Known simplifications

- Public KB is instance-wide (no per-space token) — `public` means public.
- Search is the live-FTS seam, same index; no separate anonymous rate limit
  beyond the deployment's proxy (documented).
- Attachment/image links inside public page bodies resolve only if those
  targets are themselves reachable; authors of public pages should use
  external image URLs (noted in the settings toggle help text).

## As-built notes

Shipped as specced — docs module + a forms seam, no new module. Backend:

- `doc_spaces.public` BOOL NOT NULL server_default false (models.py);
  `DocSpaceRead.public`, `DocSpaceUpdate.public` threaded through the existing
  space PATCH field loop (doc.manage — no new endpoint). Migration
  `7a1827897d5c` (from `48979a48f5b6`; the spurious `ix_doc_pages_fts`
  drop/create autogen noise deleted from both directions), applied.
- Public reads live in `docs/public.py` (service seam) + `docs/public_router.py`
  (`APIRouter(prefix="/public/kb")`, forms idiom — NO CurrentUser anywhere),
  mounted via the docs module contract. Unknown and non-public read as the
  SAME 404, so existence never leaks. `GET /spaces` returns the trimmed
  `PublicKbSpace` cards ({id, name, slug, description} — DocSpace has no icon
  field, nothing to adapt); `GET /spaces/{id}/tree` reuses `service.list_pages`
  (archived subtrees pruned by the same `core.visible_page_ids` rules) trimmed
  to `{id, parent_id, title, position}`; `GET /pages/{id}` reuses
  `service.page_read` for the breadcrumb and 404s archived pages AND pages
  under an archived ancestor (visibility check via the tree listing). No
  versions/history/links exposure.
- Search filter: `search.search_pages` grew `workspace_id: uuid.UUID | None`
  plus keyword-only `public_only`/`space_id` — one statement, the SAME
  tsvector expression + GIN index; `workspace_id=None, public_only=True` is
  the instance-wide public scope. `public.search_public` 404s a private
  `space_id` pin BEFORE searching (no probing). Authed callers (docs router,
  search deflect, MCP bridge) are untouched — the new params default off, and
  the MCP bridge binds by parameter name.
- Form deflection: `GET /public/forms/{token}/deflect?q=` on the FORMS public
  router, token-gated by the same `_form_by_token` (404 unknown / 409
  disabled). `forms/public.deflect_public_form` defers the docs import
  (feature-detected via `settings.modules`, the mailintake idiom — docs absent
  → empty docs list); top `PUBLIC_DEFLECT_LIMIT=5` (forms/types.py) pages,
  space names via `docs.public.list_public_spaces`. Response
  `{docs: [{id, space_id, title, space_name}]}` mirrors the authed deflect
  docs shape but is DEFINED in forms/schemas.py (`PublicDeflectDoc/-Response`)
  — forms imports neither search nor docs at module load. Items never
  searched.

Frontend:

- `/kb`, `/kb/$spaceId`, `/kb/$spaceId/$pageId` registered at root level
  beside `/public/forms/$token` (RoutePath.kb/kbSpace/kbPage). One route file
  `routes/public-kb.tsx`: space cards; tree rail + page with the FIRST root
  page auto-selected when the URL has no pageId. Queries are plain local
  `useQuery` + `api.get` (retry false; the endpoints never 401 so the default
  On401.redirect is inert — the public-form idiom). Chrome: Radd tile header +
  "Sign in" link. `PageTree` grew an optional `pageRoute` prop (default
  RoutePath.docPage; rows widened to a minimal structural `PageTreeRow` so
  `PublicKbPageNode` fits) and the body renders through `lib/markdown.tsx`
  (`Markdown`) — no Crepe bundle on the public path.
- Public form page mounts `PublicDeflectionPanel` (local to public-form.tsx):
  `useDebounced(title, DEFLECT_DEBOUNCE_MS)` + the min-chars gate exactly like
  the authed `DeflectionPanel`; links open `/kb/...` in a new tab.
- `/settings/docs` space edit form grew the Public checkbox + `/kb/{id}`
  copy-link row (`publicKbSpaceUrl`, the spec-62 PublicLinkRow idiom) + the
  external-image help text; `PublicBadge` chip (components/docs/) shows on the
  settings list rows and the authed space header.

Tests (`test_public_kb.py`, 7, service-driven in a rolled-back tx): public
listing excludes private spaces; private space 404s tree/page (unknown ==
private); archived page invisible in tree/page/search; search hits public
spaces only + the space pin can't probe; toggling public off immediately 404s;
tokened deflect returns public-KB hits with space names, blank-q
short-circuits, bad token 404s, disabled form 409s. Suite: 762 green; tsc +
vite build clean.
