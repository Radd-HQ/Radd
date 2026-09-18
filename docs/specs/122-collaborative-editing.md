# Spec 122 — Collaborative editing: one live document, many editors

**Status:** built (RADD-1161/1162/1163; `web/scripts/collab-proof.mjs` green in both election outcomes). **Epic:** RADD-676. **Depends on:** spec 43 (wiki), spec 27
(realtime), spec 54 / RADD-745 (the house editor chrome over Milkdown).

## What is wrong

Two people who open the same wiki page to edit see two private copies. The
second to press Save meets the spec-43 guard — "this page changed since you
opened it" — and is offered **Reload** (lose my draft) or **Overwrite** (lose
theirs). Nothing tells either of them the other is there; nothing lets them
work on one document. The guard prevents silent loss, but the choice it
offers is which person's work to throw away.

Measured today (spec 43, `pages/service.py::update_page`): the body is
markdown, saved whole by an explicit Save with `expected_version`; a version
row per content-changing save; realtime tells other readers *that* the page
changed, never *what*, and carries nothing back from a client. There is no
presence anywhere in the product.

## What changes

While a page is being edited, **the document is a CRDT shared by everyone
editing it**, and the markdown in `pages.body` is written *from* that
document. Each editor sees the others' text and cursors as they type; a
person merely reading the page sees who is editing it and gets the saved
text within seconds through the realtime layer that already exists.

Three parts, each a slice.

### 1. The room — server (`collab` module)

- **A room per page**, in the API process, holding a Yjs document (pycrdt).
  Clients speak the y-websocket protocol (sync step 1/2, updates, awareness)
  over `WS /api/v1/collab/pages/{page_id}`, authenticated by the session
  cookie exactly as `/ws` is (spec 27), re-validated on the same interval.
  Joining as an **editor** requires `page.write` through the same
  `page_access.guard_page` the PATCH route uses; joining as an **observer**
  (awareness only, no document updates accepted) requires `page.read`. The
  anonymous principal never joins: it keeps the spec-27 invalidation it has.
- **Persistence.** Table `page_collab_docs(page_id PK, state BYTEA,
  page_version INT, updated_at)`: the encoded Yjs state, written debounced
  after updates and when the last client leaves, tagged with the
  `pages.version` it corresponds to. A room opening with a stored state whose
  `page_version` equals the page's current version resumes it; any other
  state is discarded — the page was written by something that was not this
  room (an importer, an MCP `update_page`) and the markdown is the truth.
- **Seeding, once.** An empty room grants the *first* joiner the right to
  seed the document from the current markdown (a control frame before sync);
  every later joiner waits for sync. Without the grant, two simultaneous
  first joiners would both seed and the page would double.
- **The write guard.** While a room has a connected editor, a body write
  that did not come from the room (a REST PATCH with a stale or absent
  `expected_version`, an MCP `update_page`) is refused with 409 naming who is
  editing. This is the rule the user asked for by name: nothing can publish
  over live work. Implemented as a hook the `pages` service dispatches before
  a body write, so `pages` never imports `collab` (rule 1; `collab`
  `depends_on` `pages`).
- **Process model, stated.** Production runs one API replica and one uvicorn
  process (`values.yaml`, no `--workers`), so an in-process room is correct
  today. Two replicas would need either sticky routing of `/collab/*` or a
  shared relay; that is filed as the constraint, not built.

### 2. The editor — SPA

- `@milkdown/plugin-collab` (7.21.3, matching the installed kit) binds the
  ProseMirror document to a `Y.XmlFragment`; `y-websocket`'s provider talks
  to the room. Remote cursors and selections render with the house tokens;
  the Yjs undo manager replaces the history plugin *in collaborative mode
  only*, so undo undoes your own edits, not your colleague's.
- **Edit mode becomes "join the room".** The Save button is gone from the
  collaborative flow: the client elected **saver** (the connected editor with
  the lowest awareness client id — deterministic, re-elected on leave)
  autosaves the serialised markdown 1.5 s after the last change and when it
  leaves, with `collab_session` set so the server skips the
  `expected_version` check. Every other client saves nothing. The button
  reads **Done**, and leaving flushes.
- **History stays readable.** Autosaves that change the body bump `version`
  as today, but a `page_versions` row is written only when the previous
  snapshot is older than `page_collab_version_window_seconds` (default 300)
  or the save is the session's final one — a person's history is a list of
  work sessions, not of pauses in typing. Non-collaborative saves are
  unchanged: one row per save.
- **Presence everywhere.** The page header shows the avatars of everyone in
  the room, in read mode too (readers join as observers). A reader opening
  Edit joins as an editor and sees the live text immediately; the
  spec-43 conflict dialog is reached only when the room cannot be joined
  (socket refused), where the old single-editor path still works.
- Inline comment anchors (text-quote selectors, client-resolved) need no
  change: they re-locate on each saved body as they do today.

### 3. The proof

`web/scripts/collab-proof.mjs`: two browser profiles signed in as two users
edit one page. Asserts: each sees the other's text within a bounded delay;
each sees the other's cursor and avatar; a reader sees "2 editing" and the
saved text after the autosave; a REST PATCH from a third session is refused
with 409 while they edit and succeeds after both leave; the version history
grew by one row for the session, not one per keystroke burst; reload
mid-session rejoins with the document intact; a server restart with a stored
state resumes it.

## Changed while building (server half, RADD-1161)

- **Two hooks, not one.** The pre-write hook (`page.body_writing`) is as
  specified; a second, `page.version_bumped`, was needed so the room can
  track the version its stored state corresponds to after a save it made,
  and so a body write by something else — only possible while no editor is
  connected, but observers may be — RESETS the room (clients closed `4409`,
  stored state discarded) instead of leaving a stale document for the next
  editor to sync and then autosave over the new markdown. The version-mismatch
  rule at room open covers restarts; this covers the in-memory room.
- **The seed grant goes to editors only.** An observer cannot send the update
  that would seed, so granting it one would waste the grant's window.
- **Auth on inbound frames is throttled** (`collab_frame_auth_seconds`, 5 s):
  a session lookup per keystroke frame would put the database behind the
  cursor. The absolute `realtime_session_refresh_seconds` deadline is kept
  exactly as spec 27 has it.
- **Persistence is serialised**: a flush racing the debounce timer waits for
  the save in flight; rescheduling cannot cancel a save under way.
- **The room's observer filter lives in the channel adapter**, not in `YRoom`:
  `YRoom.serve` applies every sync frame it is handed, so the role is enforced
  by what the iterator yields.
- Wire: `POST /api/v1/collab/pages/{id}/join` → `{session, role, seed,
  page_version}`; `WS /api/v1/collab/pages/{id}?session=`; close codes `4401`
  (cookie), `4403` (session unknown / not yours / room gone — rejoin), `4409`
  (document replaced — rejoin). The saver must send its `final` save BEFORE
  closing its socket, or the save is an ordinary one (`expected_version`
  enforced, a row per save).

## Changed while building (SPA half, RADD-1162, and the proof)

- **The saver serialises the bound document itself.** Milkdown's listener
  skips any transaction flagged `addToHistory: false`, which is exactly how
  y-prosemirror applies a REMOTE change — so `onChange` never learned what
  the other person typed and the elected saver wrote a draft that stopped at
  its own edits. In a room, RichEditor re-serialises after every document
  update (150 ms debounce) into the draft the saver reads.
- **The room sends its awareness snapshot to a newcomer and answers the
  provider's query.** pycrdt's `YRoom` relays awareness but neither sends
  existing states at connect nor answers the y-websocket `queryAwareness`
  message, so a second joiner elected itself saver until the first client's
  next heartbeat — two savers for up to fifteen seconds. Both are done at the
  channel.
- **Unbind before destroy.** The provider outlives the editor for the final
  save; a remote change or awareness update landing on a destroyed Milkdown
  context threw. The editor disconnects the collab service before destroy.
- **Only the server's 44xx band is a refusal.** A navigation or network close
  is the provider's own reconnect business; 4403/4409 join again, bounded.
- The proof reads the election from the DOM and has the saver type FIRST,
  then the other person — the order that failed — so it does not depend on
  which client the random client id favours. The server-restart resume is not
  driven by it; the test suite covers the stored-state rule.

## Rejected

- **Presence only ("someone else is editing") with a lock.** Cheaper, and the
  owner said he prefers working together. Presence ships here anyway, as a
  side effect of awareness.
- **ProseMirror `collab` (central rebase server).** Fewer dependencies but a
  server-side ProseMirror schema to rebase against, which means running the
  editor's schema in Python or Node; the CRDT needs no schema on the server.
- **Server-side markdown serialisation.** Would let the server own the save,
  but the serialiser is Milkdown's and lives in the SPA; duplicating it in
  Python is the drift the SLQ rule warns about. The elected saver keeps one
  serialiser.
- **A version row per autosave.** Complete but useless: a two-person hour
  would produce hundreds of near-identical revisions.
- **Co-editing issue descriptions.** Items have no `expected_version` and no
  version history (PLAN §5.5: only wiki docs pay the collab cost). Presence
  on the description editor is a cheap later slice on the same room seam.

## Where

`server/src/radd/modules/collab/` (new: router, room hub, store, write
guard hook, types); `pages/service.py` (the pre-write hook, `collab_session`
+ the version window); migration `page_collab_docs`;
`web/src/components/editor/collab/` (provider, presence, saver election);
`PageView.tsx`; `docs/modules.md`; `deploy/helm` values comment on replicas.

## Done when

Two browsers edit one page concurrently and never see a version-conflict
dialog; each sees the other's text and cursor; a reader sees who is editing
and the saved text; an outside write during a session is refused and
succeeds afterwards; history shows one revision per session; the proof above
is green; `uv run pytest` and the web gates stay green.


## Addendum (RADD-1244): the version counts history rows

The first cut bumped `version` on every autosave and coalesced only the
history rows, so a page could read **v4** in its header while History
offered v1 alone — v2 and v3 had never been rows. The number people see
must count what they can open, so the bump moved UNDER the snapshot: a live
autosave inside the window writes the body and nothing else (`version`
unchanged, `PageHook.BODY_AUTOSAVED` dispatched), and the row + bump happen
together — on the first save of a window, on the session's final save, and
now on a third path: **the seal**. A session that ends without its final
save (a crashed tab, a dropped socket, a process stop) leaves autosaved
content with no row and an unmoved version, which is exactly the state where
a REST client holding the old number would pass `expected_version` and
overwrite text it never saw. The room remembers the unsealed autosave
(`Room.unsealed`) and, when it drops or the hub shuts down,
`pages.service.seal_history` writes the row for the current content and
bumps. Every session therefore ends with a bump, by the client or by the
server, and the concurrency token is as strong as before. The History tab's
"grouped versions" note shipped the same day was removed: there is nothing
to explain any more.
