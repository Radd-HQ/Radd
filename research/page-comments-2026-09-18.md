# Page annotation navigation — RADD-1225

The reported behavior had three causes:

- `PageView` mounted inline comments after the entire document and only in read mode.
- Selecting a thread changed its highlight without scrolling to the selected passage.
- Code blocks contain both virtualized CodeMirror lines and hidden ProseMirror source. Walking all text nodes counted code twice and could locate a quote in invisible text.

The local change places annotations in a sticky right sidebar when the page has enough room. Narrow layouts use a bounded, scrollable panel above the document. The panel remains available while editing. Quoted passages are keyboard-accessible buttons; clicking a highlighted passage reveals its thread. General page discussion remains below the document.

Code blocks now supply one stable source and an adapter to the visible CodeMirror positions. Navigation materializes an offscreen code line before measuring it. Selection maps back to that same source. The adapter is removed when the editor is destroyed; no annotation markup is inserted into the document.

Missing or ambiguous quotes remain visible as detached comments with navigation disabled. Root comment semantics and collaboration transport are unchanged. RADD-1226 adds persisted replies with inherited access checks and bounded pagination.

Validation:

- `npm run build` — TypeScript and production bundle.
- `npm test` — 26 tests, including quote anchoring and collaboration saver election.
- `npm run test:browser` — existing shell, autocomplete, issue rendering, and sign-in regressions plus the new page-comment fixture.
- `browser-page-comments.mjs` covers a 45-section document, a 101-line code block, desktop and 390px layouts, prose/code jumps, keyboard activation, passage-to-thread navigation, code selection, detached/ambiguous anchors, resolve/reopen, and updates after editor input.

The browser fixture uses synthetic HTTP data and the single-editor fallback. It does not establish a real multi-user collaboration session, so it does not revalidate WebSocket synchronization. The annotation observer watches the same editor DOM used by collaboration.

This change is local and has not been released. The preceding sign-in change is already live in v0.42.2.

## Hover and reply follow-up — RADD-1225 / RADD-1226

Hovering an annotated passage opens a preview near the pointer, without fetching replies or moving editor focus. Clicking pins the conversation there. The panel is clamped to the viewport; Escape, an outside click, or document scrolling dismisses it. Moving into the preview keeps it open. Reply drafts survive popup dismissal while the page remains mounted.

Replies are flat children of the anchored comment. The database relationship cascades on deletion; root feeds omit children and batch reply counts. Opening a thread requests its latest 50 replies, with older pages available on demand. The root's current page access and comment audience govern all reply reads/writes. Resolved conversations stay readable and must be reopened before another reply. Existing comment-created events carry replies through the normal event path.

New coverage includes real database/HTTP reply persistence, attribution, pagination, access refusal, resolve/reopen, root deletion, blank replies and malformed cursors. Browser coverage includes hover without requests, pointer-to-popup movement, pinned conversations, preserved drafts, failed-post retry, successful posting, Escape and mobile viewport bounds.

This follow-up requires migration `d1226threads` before running the updated backend. Production is unchanged.

Final follow-up validation: production build and 26 frontend unit tests passed. All browser regression scripts passed; the login fixture was corrected to wait for the failed directory response before clicking the recovery link. The full backend run passed 2,824 tests with 4 skips and identified the required anonymous-route inventory addition. After registering the new read route and adding an actual public/private/anonymous HTTP test, all 38 affected comment and anonymous-surface tests passed. The local database is at `d1226threads`, and the restarted local server exposes both reply routes and passes its health check.
