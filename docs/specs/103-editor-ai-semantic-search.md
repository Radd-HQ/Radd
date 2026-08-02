# Spec 103 — editor AI actions + semantic search

**.** The two visible halves of the AI platform: Crepe's AI feature
streaming server-curated writing actions with diff review, and meaning-based
retrieval on pgvector fused into every search surface.

## Editor AI

- **Backend**: `GET /ai/editor/actions` (builtins refine / format / summarize
  selection / fix-grammar + enabled spec-101 presets — ids and labels only,
  prompts stay server-side) and `POST /ai/editor/stream` — SSE with JSON
  frames (`data: {"t": …}`, `event: done`, in-band `event: error`, since
  headers are gone when upstream fails). Gated by the editor_actions feature
  (404-dormant); the abort chain runs Crepe AbortSignal → fetch abort →
  generator cancel → upstream httpx close. `CommitBeforeSendMiddleware` passes
  `text/event-stream` through instead of buffering — buffering would have
  silently defeated streaming.
- **Frontend**: Crepe 7.21.3's own AI feature (previously `AI: false`) with a
  custom provider consuming the SSE via fetch+reader (`lib/sse.ts`); the
  selection Toolbar turns on with it (that's where the AI entry lives). Menu =
  server actions via a `#radd-action:` instruction sentinel; freeform prompts
  pass through. `diffReviewOnEnd` — AI never silently replaces text. Gate =
  instance feature AND per-user preference, resolved inside RichEditor, so
  every call site (issue description, comments, wiki, new-item modal) got it
  with zero per-site edits and OFF renders exactly the pre-103 DOM (proven by
  a two-phase CDP render proof). PlainEditor deliberately has no AI in v1.

## Semantic search

- **pgvector**: compose/dev images moved to `pgvector/pgvector:pg16`; a guarded
  migration creates the extension where available; the embeddings schema is
  RUNTIME-managed (`ensure_schema()` startup hook, outside Base.metadata) so
  Alembic autogenerate stays quiet on plain Postgres and an image swap after
  migration needs no re-migration. The HNSW index is an expression-cast
  PARTIAL index per active model (`(embedding::halfvec(dim)) WHERE model=…`) —
  a model swap needs no migration: the embedder rebuilds the index and the
  sweep re-embeds.
- **The embedder** (`ai.embedder` consumer): item/comment/doc events re-embed
  their entity; ONE reconcile sweep (anti-join on model) is backfill + silent-
  event coverage + model-change re-embeds — silent Jira imports reach
  `search_index` (the search indexer deliberately doesn't skip them), so the
  sweep sees them as missing. Do not "fix" the head-seeded silent-skip; the
  sweep converges it. Text flows through two seams — `search.rows_for_embedding`
  (public text only BY CONSTRUCTION: internal comments never enter
  search_index) and `docs.pages_for_embedding` — each module querying only its
  own table, the other referenced by name. sha256 content-hash skips no-ops.
- **Fusion**: `search/fusion.py` RRF (k=60). `/search` fuses FTS with vector
  ANN for non-key queries ≥8 chars — RBAC pre-filtered in SQL with
  `hnsw.iterative_scan = relaxed_order` so narrow-access users still fill the
  page; time-budgeted (2s) and FTS-only on ANY failure. Similar-issues fuses
  vector neighbors (stored embedding, fallback on-the-fly) with the FTS pool
  before the optional LLM rerank. KB deflection fuses the docs half.
- **Surfaces**: the palette's **Ask mode** (`GET /search/semantic` — pure
  meaning retrieval over items + docs, `enabled: false` when unconfigured) and
  a new **MCP `find_items` tool** routed through `search.service.search`, so
  every MCP agent inherits hybrid ranking — and any future ranking upgrade —
  with no client change. (Verified: the pre-existing `search_items` tool is
  SLQ, not text; without `find_items`, agents would never have touched the
  hybrid ranker.)

## NL→SLQ value repair (addendum)

"jimmy's tasks" generated `assignee = jimmy` — and for most entity fields an
unknown value doesn't even error: it COMPILES into a correlated subquery that
matches nothing (silent empty results). SLQ stays exact — a typo in a saved
view must never silently match someone else — so the forgiveness lives in the
NL layer only: after the model drafts a query, a pre-compile AST walk
(`ai/nlrepair.py`) resolves every entity value against the LIVE candidates the
autocomplete seam already serves (users, states, labels, projects, teams,
cycles, releases, issue types, custom select options; spec-97 plugin user
fields borrow the people candidates) and swaps in the closest real value —
token-aware deterministic string matching (`ai/fuzzy.py`, diacritic-folding,
first-name-over-surname tiebreak; deliberately NOT embeddings: short proper
names are lexical, and this works with the AI roles off). Users match on their
display NAME and the query gets their EMAIL. Repaired values re-render QUOTED
(never re-read as sentinels); `me`/`none`/dates/booleans/item keys/`~`
substrings are never touched; below the confidence threshold the value is left
alone so the honest empty result stands. Every substitution is appended to the
explanation ("Matched 'jimmy' to Jimmy Lee Barlow (jb@…)"), and the system
prompt now tells the model to use the user's words verbatim rather than invent
emails. Side fix: `type` was the one entity field with no autocomplete value
source — it now serves issue-type names.

**Dialect-aware** (same day): `POST /slq/nl` takes `dialect: items | worklog`.
The timesheet's AskAiBar sends `worklog`, whose prompt teaches the spec-98
surface (bare author/category/project/worked_on/time/note, `issue IS EMPTY`,
and item fields ONLY behind `issue.` — custom keys render as `issue.<key>`),
validation compiles through `compile_worklog_query`, and the repair pass
resolves worklog bare fields (author → people, category → work categories,
project → keys) and strips `issue.` before sourcing delegated item candidates.
The user prompt also anchors "Today is <ISO date>" — without it the model
guessed "this month" from training data (seen live: 2025-05-01).

## Addendum — the editor-AI UX wave

Dogfooding surfaced that v1's ONLY entry point was Crepe's selection-triggered
floating toolbar in edit mode, and that its diff review rendered one
Accept/Reject pair per raw changeset chunk — character-granular, so an AI
rewrite produced a wall of buttons and mid-word fragments ("~~D~~d emo").
Three additions, one fix:

- **Toolbar AI button** (`buildTopBar` into Crepe's first group, our
  `AiActionPicker` popover): curated actions + freeform prompt, applied to the
  selection when there is one, else the WHOLE document
  (`runAiOnEditor` — a whole-doc TextSelection, then Crepe's RunAI command
  **dispatched by NAME**: importing `runAICmd` from the subpath entry binds a
  second module instance whose `.key` never initializes, since `$command`
  assigns it at plugin run time and only the root entry's copy runs).
- **Read-mode AI menu** (`AiReadMenu` on rendered comments, the description,
  and wiki pages): query actions answer in the popover — Find similar issues
  (`POST /ai/similar` for text seeds: `similar_to_seed`, the same FTS+vector
  fusion, never reranked since there is no source issue; the item-seeded
  endpoint for the description) and Summarize (the editor stream, rendered
  not applied). Transform actions + freeform hand off via `initialAiRun`: the
  edit session opens with the run streaming in as a reviewable diff.
  Transforms are offered only where the actor can write (spec-96 discipline).
- **Per-block diff review** (`web/src/components/editor/diff/`): RichEditor
  swaps Crepe's diff decoration plugin (`editor.remove(...)` pre-create) for
  a fork that groups inline changes per enclosing TEXTBLOCK — the paragraph
  inside a list item, NOT the whole list (which is why config-only
  `customBlockTypes` couldn't do it: its merge expands to top-level blocks) —
  one controls pair at each changed block's end, visual runs expanded to word
  boundaries by swallowing unchanged characters shared by both docs
  ("~~Demo~~ demo"; accept/reject still applies the EXACT ranges).
  Block-level/custom-block changes keep upstream's rendering. Same
  `milkdown-diff-*` classes, so Crepe's theme CSS is untouched.
- **Whole-issue summarize** (same wave): `summarize_item` sections are now
  char-BUDGETED (`take_recent`, pure + tested: newest entries kept whole until
  the section budget runs out — a long thread contributes its recent hundred
  comments, not its last twelve) and gained a **time-tracking digest**: total
  logged/estimate/remaining, a per-person split, and the newest entries
  (date, author, category, duration, note) via `timelogging.item_summary`
  behind a deferred feature-detected import. When timelogging is absent, off
  for the project, or empty, the digest is `[]` and the prompt section never
  appears — the model is never told about a facility the instance doesn't
  use; the system prompt asks for an effort line only "when a Time tracking
  section is present". The description's read-mode menu runs THIS endpoint
  ("Summarize issue") instead of text-only summarize; comments and wiki pages
  keep the per-block text stream.
- **Upstream reject bug fixed in the fork**: the diff plugin's overlap test
  (`fromB < r.toB && toB > r.fromB`) can never match a pure DELETION
  (`fromB === toB`) — upstream's Reject button is a silent no-op on
  deletion-only chunks. All fork rejects dispatch the range padded by one
  position per side; the padding only reaches into the ≥1-token unchanged gap
  that always separates changes, so it cannot capture a neighbour.

## Known simplifications

Custom fields are not embedded (parity with FTS). A silent content change to
an ALREADY-embedded row waits for the next event or model change. Editor
streaming has no rate limiting yet (nothing in the codebase does). The diff
fork tracks upstream `@milkdown/components` ~7.21 semantics; a Milkdown
upgrade that reworks the diff plugin needs a manual re-port (three files,
provenance comments point at the sources). A whitespace-only block change
(the AI dropping a blank line) renders as a bare controls pair on a dashed
empty block — honest but terse.
