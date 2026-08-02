# Spec 106 — Form assist: rich descriptions + similar issues on every submission form

User ask: the submission forms still had a plain `<textarea>` for the
description; it would be nice if the form searched similar issues and popped a
panel beside the form (like Summarize / Find similar elsewhere), and if AI
features were available to the submitter.

Audit first: there are THREE submission surfaces, and they were uneven —
internal (`/p/KEY/forms/…`, authed, had NO deflection at all), portal
(`/portal/forms/…`, authed requesters, title-only KB deflection), public
(`/public/forms/{token}`, anonymous, docs-only FTS deflection). None had the
editor; none ever called `POST /ai/similar`.

## Decisions

- **Authed pages get the full treatment; the anonymous public page gets the
  editor MINUS AI** (user-picked). The public token never expires, nothing is
  rate-limited, and every `/ai/*` endpoint is authenticated — exposing AI
  there means unmetered LLM spend and issue-title leakage to anyone holding a
  URL. Deflection stays docs-only on public (resolved issues stay internal).
- **A dialect of the issue page's results pane, not a copy**: the assist panel
  is LIVE (seeded from the draft as it's typed), where `AiResultsPanel` is
  run-on-demand — so it's a new `FormAssistPanel` composing the existing
  pieces (`DeflectDocsSection`/`DeflectItemsSection` extracted from
  `DeflectionPanel`, `SimilarCandidatesList`) rather than a reuse of the
  request/run machinery.

## Frontend

- **`RichEditor` grew `anonymous`** (`web/src/components/editor/RichEditor.tsx`):
  skips `useEditorAi` entirely (the gate queries — `/ai/status`,
  `/auth/me/preferences`, `/ai/editor/actions` — are authenticated, and the
  api client answers 401 with a redirect to /login) and never registers the
  `@`/`#`/`/` trigger plugin in either mode (user directory + issue search
  are logged-in surfaces). `useEditorAi(enabled)` mounts NO queries when
  disabled. Formatting only; OFF is still byte-identical markdown.
- **`FormDescriptionArea` renders `LazyRichEditor`** (shared by all three
  pages — the internal page's duplicated inline textarea block is deleted).
  No image upload: the item doesn't exist yet. Editor AI on the authed pages
  arrives through the existing gates, nothing form-specific.
- **`FormAssistPanel`** (`web/src/components/forms/FormAssistPanel.tsx`),
  authed pages: KB docs + previously-resolved (the deflect endpoint, title
  seed — FTS ANDs tokens, so the short title is the right seed) + **Similar
  issues** via `POST /ai/similar` seeded with the WHOLE draft
  (title+description, debounced 800ms — each probe embeds server-side; capped
  8k chars), gated on `/ai/status`, deduped against the resolved list, query
  KEYED on the debounced text (a draft must refetch as it grows — unlike the
  read-menu's stable `seedKey`). Every link opens a new tab: the half-typed
  form must survive the detour (`SimilarCandidatesList` grew `newTab`).
- **Two-column layout on all three pages**: form column + sticky aside.
  Internal/portal use `@container`/`@5xl` (the sidebar collapses, so viewport
  width lies); the standalone public page uses plain `lg:`. The panel mounts
  TWICE (inline under the title on narrow, aside when wide) — same query
  keys, so the twin is free; visibility swaps via `hidden`/`@5xl:block`
  wrappers. The public page's aside is its existing tokened docs panel,
  restyled onto the shared `DeflectDocsSection kb`.

## Backend (fusion parity — both were flagged gaps from spec 103)

- **`search/deflect.py`: the items half now fuses semantic candidates** like
  the docs half (deferred ai seam, `[]` on any failure, RRF). Semantic
  additions RE-PASS the project + resolved-state filter — nearest-neighbour
  has no notion of state, and an OPEN lookalike is a duplicate, not an
  answer (the assist panel's Similar section is where those belong).
- **`docs/public.py: deflect_public`** — `search_public` fused with
  `doc_candidates(public_only=True)`; the tokened form deflect calls it.
  Deliberately a SEPARATE function: the public KB search box stays plain FTS
  (an anonymous, unthrottled surface shouldn't spend an embedding per
  keystroke; the form panel is client-debounced and worth it). Every
  semantic addition re-passes LIVE `public` + non-archived filters via
  `pages_by_ids(public_only=True)` — the vector store's `public` flag is a
  COPY taken at embed time, so a space flipped private since must not leak.
- **Layering**: forms must not import search (standing rule in
  `forms/schemas.py`), so the public fusion lives in docs — which imports
  `search.fusion.rrf_fuse` deferred (pure, kernel-bound machinery: the SLQ
  "import, never copy" rule) and the ai candidates seam feature-detected
  (`docs/types.py:AI_EMBEDDINGS_MODULE`).

## Follow-up (same day): similar went SEMANTIC-FIRST

Dogfooding the panel showed the text half matching aggressively-unrelated
issues: `similar_to_text` ORs every seed token (deliberate, for partial
overlap), so one shared common word ("auto", "working") was enough to rank an
unrelated issue — and `fts_candidates` normalizes by the TOP rank, so the
best FTS hit always displayed as a "100% text match" however weak it was in
absolute terms. Fix (user-picked over overlap-gating): `similar_to_seed` and
`similar_items` now use the vector pool ALONE when the embedding half is up —
the OR-ed FTS pool (and its rank-relative scores) runs only as the fallback
when semantic is off/unconfigured/empty. `fuse_pools` deleted (dead); /search
and both deflection halves keep their RRF fusion (their FTS is AND-ed, so it
stays precise). Trade-off accepted: rare literal terms (an error code) now
surface only through embeddings when semantic is on.

## Tests / verification

`test_desk_polish.py`: items-half fusion (open lookalike filtered) + degrade
to FTS on seam failure. `test_public_kb.py`: public fusion (private page the
mocked vector store offers is re-filtered live; `public_only=True` asserted)
+ degrade. 1241 total. CDP render proof (three pages, 1600px): editor + AI
toolbar mount on authed pages, panel measured BESIDE the form; the anonymous
page stays on its URL, mounts the editor WITHOUT the AI entry, and its
recorded fetches touch only `/api/v1/public/*`.
