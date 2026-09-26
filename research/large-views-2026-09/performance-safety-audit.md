# Performance changes: functionality audit

> Point-in-time change log, 2026-09-17 (RADD-1204–1212); moved from `docs/` on 2026-09-27. It does not describe the current tree.

User authorization: implement the proposals after auditing breakage; exclude
variants that lose functionality. RADD-1204/1205/1206 track the existing work.
This ledger distinguishes implemented changes from unsafe variants left out.

| Proposal | Concrete failure mode to prevent | Decision before implementation |
| --- | --- | --- |
| A1 grouped SQL | Different group order; filtering after paging; leaking private ancestors | Remove unused ranks/joins only; retain authorization builder and stable tie-breaker; prove page/order/visibility parity |
| A2 aggregates | Loaded-row progress changes on Show more; hidden point fields leak through sums | Reuse authorized full-cycle stats; never total a partial bucket as a full group; batch only through the same permission contract |
| A3 compact responses | Shared Item cache/editor/export/plugin loses description or relations | Do not substitute partial objects into full Item caches. Requires a separate typed projection and complete consumer inventory; exclude the incompatible shortcut |
| A4 supplementary cache | Time/state edits leave stale numbers; account changes leak cached values | Reuse chunks only with entity invalidation and account cache isolation intact; do not give values independent permanent caches |
| B1 column loading | Other groups advance; unavailable rows look like empty columns; Load all floods browser | Independent explicit windows; retain full counts and order; do not silently truncate or claim a cap is Load all |
| B2 virtualization | Browser Find, keyboard ranges and native drag/drop lose offscreen DOM targets | Do not unmount interactive offscreen rows without equivalent behavior; investigate browser rendering containment as a preserving alternative |
| B3 independent states | Partial failure blanks healthy sections; cached query shows wrong scope | Keep section-specific pending/error states and keys; restore position only within identical view/filter/sort scope |
| C1 My Work | Sorting after limit omits urgent work; counts pretend a preview is complete | Server-order and limit previews; full count and route to all matches required |
| C2 children | Sorting each page independently puts completed children before unseen open work | Server-order before paging; preserve full direct-child count and descendant rollup distinction |
| C3 refresh scope | Custom SLQ membership/permission changes missed by guessed dependencies | Keep conservative item/access invalidation until dependency metadata is complete; retain existing query-scoped websocket handling |
| D1 cursors | Numbered-page navigation and arbitrary custom/null sorts no longer work | Do not replace the current API. New optional cursor mode needs explicit sort contracts; exclude the incompatible replacement |
| D2 roadmap | Dependencies, box selection, drag hit-testing and print rely on complete rows | Keep complete scheduling model/DOM behavior; do not drop dates or dependencies outside the viewport |

Safety checks: permission and field-visibility parity, pagination with uneven
groups, stable totals, search beyond the first slice, selection and drag/drop,
keyboard focus, changed data and account isolation. Tests alone do not establish
production speed; record comparable local profiles separately.

## Implemented outcome

- **A1 / RADD-1204:** remove redundant global ranking from the selected-cell
  query and ancestor joins when not grouping by epic. One comparable local
  direct-service profile over 501,297 authorized rows fell from 6,633 ms to
  3,493 ms (about 47%). Query count remains 210; this is not a production SLA
  or evidence that all permission/hydration costs are solved.
- **A2 / RADD-1205:** sprint progress shares the existing authorized cycle
  statistics request; project scope is retained. These are whole-sprint numbers,
  intentionally unaffected by row filters. Board point totals are computed in
  the full grouped count query; restricted fields return no aggregate.
- **B1 / RADD-1205:** ordinary board columns can request their own next 25 rows,
  retry locally, and retain other columns. Full counts and points stay visible.
  Existing matrix/group paging remains for swimlanes. Unbounded Load all is
  excluded: current cards retain DOM, and the recorded 2,000-row browser probe
  already had a 514 ms long task. A future cancellable loader needs a rendering
  solution that preserves Find, selection, and drag targets first.
- **B3 / RADD-1205:** independent Planning pending/error/retry states allow healthy
  sections to render during a slow or failed request. No new scroll-restoration
  mechanism: restoring offsets against changed membership/order can land on
  unrelated work; existing navigation behavior remains.
- **A3/A4 / RADD-1206:** full Item objects remain intact. Selective gzip for GET
  item collections reduces bytes without changing JSON contracts; auth, streams,
  files and mutations bypass it. Existing proxy encodings are respected. Stable
  supplementary chunks reuse earlier requests on append, while item/worklog
  invalidation and account cache clearing remain authoritative. Rollup/SLA data
  now reaches rows beyond the first 200. Compression trades some server CPU for
  fewer bytes and may add no benefit behind an already-compressing proxy.
- **C1/C2 / RADD-1208:** My Work begins with 25 due, 25 other assigned and 8 starred
  issues, with full counts and Show more. Default urgency sorting happens before
  the limit; explicit user ordering takes precedence. Children load on expansion
  in pages of 50. Their server workflow category/state ordering replaces the old
  client category/key comparator, so within-category state order can change.
  Complete-relation scheduling readers are unchanged. Full child/descendant
  counts are not inferred from loaded rows. The tradeoff is extra clicks to see
  all rows and counts may arrive after the preview.

**Excluded incompatible variants:** partial objects in shared Item caches (A3),
DOM-removing virtualization or unproven containment that clips popovers (B2),
guessed mutation dependencies that miss custom SLQ membership changes (C3),
replacing numbered pages/custom sorts with cursors (D1), and viewport-only
roadmap data that loses offscreen dependencies/selection/print (D2). These are
future designs, not completed optimizations.

Regression evidence: database grouped-page/order and field-visibility tests;
compression identity/encoding/allowlist tests; stable append/prune and mutation
invalidation tests; built-browser grouped board/queue, Planning (including a
blocked recovery response), and My Work/children proofs. The Planning proof also
covers search beyond the first page, full progress under completed-row filtering,
range selection, keyboard focus, drag/drop and mobile controls. Screenshots were
inspected locally. Fixture tests establish behavior, not deployed performance.

## Hybrid follow-up approved: RADD-1209

Optional cursor continuation is now used for My Work, expanded direct children,
and ordinary board columns. Existing numbered lists/backlog, matrix paging and
Planning's sprint stream retain their current navigation. The Show more UI is
unchanged; aggregate statistics are independent. Tests cover mixed directions,
nulls, workflow ordering, custom numeric fields, deleted anchors, insertion before
the boundary, scope mismatch and permission checks on subsequent requests.

This addresses the safe optional mode discussed under D1, not a wholesale cursor
replacement. Large custom-text boundaries use a bounded encrypted offset token
instead of emitting an unusably long URL. Mutable sort values still mean this is
not snapshot isolation. No new indexes or production latency guarantee are
claimed; complicated filters, authorization and full counts can remain expensive.

## Board navigation replacement: RADD-1212

Approved after the group-pager usability review. Board summaries and individual
cell windows now have distinct request modes. RADD-1217 extends this model to
grouped lists, with independent scrolling sections and a searchable group picker. Complete column/lane identities come from summaries rather than loaded
cards. The summary avoids global issue ranking; single-cell reads use direct
UUID predicates, limit+1 and the existing authorization-bound cursor machinery.

Local read-only backend probes (different requests, not an equivalent full-page
benchmark): the former all-project assignee group switch fetched 500 cards in
6.9 seconds, including 4.9 seconds of aggregate/ranking work. The new summary
took 1.0 seconds; individual 25-card requests took 0.30–0.84 seconds in the sampled
columns. State/assignee summaries took 1.56 seconds. Actual network/browser and
scope costs vary; these are not production latency guarantees.

Browser proof verifies visible-first loading, full totals/points, independent
scrolling, automatic continuation, local retry retaining prior cards, searchable
column jumps, preserved scroll position, drag/drop and complete swimlane
structure. Permission and field-restriction tests exercise both summary and
row modes. No aggregate cache shared between users was introduced. No card
virtualization was introduced; previously loaded cards remain accessible, so
extremely deep exploration still grows the DOM. Changes to filter/sort reset
loading scope; ordinary horizontal navigation retains it.


---

## Appendix: large-view implementation notes (moved from `docs/modules.md`, 2026-09-27)

As recorded in the module map when each change landed; the map now describes only the result.

### Large-view performance safety audit (RADD-1204)

this file records compatibility constraints for the
approved optimization wave. Grouped reads compute global rank only for group
ordering; selected cells alone receive per-cell ranks. Ancestor joins are used
only for epic axes. Authorization, group ordering and page totals are unchanged.

### Group totals and independent loading (RADD-1205)

`items/grouped.py` accepts an optional column window and computes full point
sums alongside counts, withholding sums for restricted fields. `useBoardItems`
now shares complete summaries and per-group cursor windows between boards and
grouped lists (RADD-1212/RADD-1217). Visible groups load independently as the
reader scrolls; searchable navigation replaces group paging and bottom loaders. Planning renders section-local
loading/errors; cycle headers share authorized whole-cycle statistics instead
of computing progress from loaded rows. Row filtering does not alter those
whole-sprint totals. See this file for compatibility
limits and the browser/database regression evidence.

### Collection bytes and supplementary batches (RADD-1206)

`CollectionCompressionMiddleware` gzips only GET item collections (items,
grouped items and SLA queue) above 2 KiB, preserving full Item contracts and
existing response encodings. `useStableItemBatches` keeps prior chunk membership
on append for rollup, SLA and timelog hooks. Existing entity invalidation still
refreshes active chunks; complete scheduling timelog readers remain unchanged.
No partial shared Item projection or guessed invalidation dependency was added.

### Progressive personal and child lists (RADD-1208)

My Work requests bounded server-ordered previews with full counts and per-section
Show more (25 due, 25 other assigned, 8 starred). Due items are separated from
other assignments before pagination. `childItemPagesQuery` loads direct children
in workflow category/state order, 50 at a time on expansion, in issue detail and
board cards. `childItemsQuery` remains the complete relation for other consumers;
rollup and child counts remain independent of the number of displayed rows.

### Hybrid continuation (RADD-1209)

`GET /items?cursor_mode=true` keeps its Item array response and adds
`X-Next-Cursor`; callers send `after` for continuation, never with an offset.
`items/cursors.py` uses compiler ordering expressions, PostgreSQL null placement,
and a unique ID tie-breaker. Boundary values are encrypted with the existing
instance secretbox and bound to actor, query and structured scope. Each page
rechecks current authorization; tokens are positions, not access grants. Large
custom-text boundaries fall back to an encrypted offset token to keep URLs below
proxy limits. These rare windows retain offset pagination's mutation caveats.

My Work and expanded children use sequential cursor pages behind the same Show
more buttons. Ordinary boards receive a cursor per column and independently
continue it; invalidation rebuilds the cursor chain and cached windows are reused
on append. Numbered list/backlog and swimlane group navigation remain available.
Full count/stat queries remain separate. `target`/`start` date ORDER BY support
also fixes the Due soon query's previously unsupported target sort. Cursor
reads are not snapshots: moving an issue across the sort boundary can still
change what a later page sees. Refresh rebuilds the sequence from its start.

### Personal Starred pin board (RADD-1210)

`/starred` is an authenticated, cross-project personal card grid, linked from the
full sidebar, collapsed rail and command palette (and pinnable in the top bar).
It queries the existing actor-scoped `starred = true` filter, includes completed
issues, supports title search, status filtering and sorting, and uses cursor
Show more with separate full counts. Ordinary archived/access filters still
apply. Opening a title uses the normal peek flow and modified-click links.

`QuickStar` reuses the existing personal star API on board cards, list/Planning
rows, My Work and the pin board. The button is visible without hover, keyboard
accessible and isolated from parent click/drag actions. It shows the requested
state while pending, disables duplicate writes until cache reconciliation and
reports failed saves. Personal stars require read access, never shared edit
rights; starring does not change workflow state or a shared board's order.
Proof: `web/scripts/starred-proof.mjs` (toggle, keyboard isolation, failed writes,
completed rows, cursor paging, cross-page search, filters, rail and mobile layout)
and `server/tests/test_personal_starred.py` (per-user isolation and completed pins).

RADD-1211 adds a List/Cards switch to Starred. The presentation preference is
stored per account in this browser, with cards as the initial default. Both
layouts share the same query, filters, loaded cursor windows and personal-star
actions; changing layout does not refetch the issue collection. The list shows
key/title, status, priority and owner in aligned desktop columns and wraps into
compact rows on narrow screens.

### Stable board navigation (RADD-1212)

Boards now use `useBoardItems`, separate from grouped-list paging. On
`GET /items/grouped`, `summary_only` returns complete authorized totals, point
sums and a small group directory without hydrating cards or ranking all matching
issues. `grouped_labels.py` resolves only keys from that authorized aggregate
through the existing auth/teams/projects/items spine. Readable-ancestor guards
also cover epic directory entries. `grouped_axes.py` keeps direct UUID predicates
on indexed fields for individual column reads.

`rows_only` requires a complete column/lane key, reads limit+1 ordered IDs and
returns an actor/scope/cell-bound cursor. It does not recount groups. Both paths
retain SLQ, row visibility and field-read guards. The ordinary grouped-list
contract and numbered list pagination remain available.

`ViewBoard` keeps stable columns with a searchable navigator, fixed headers,
independent vertical scrolling and automatic cursor continuation. Its column
statistics cover every matching issue, not loaded cards. Cursor windows are
separately cached; appending does not replay earlier windows or the summary.
`ViewSwimlanes` retains complete lane headers and delays mounting off-screen
lanes; visible cells fetch independently. Visited content stays mounted to
preserve native selection/find/drag behaviour. `BoardLoadBoundary` observes
clipping ancestors, stops on failures and offers local retry. Drag edge scrolling
is shared in `board-scroll.ts`. Group paging controls now belong only to grouped
lists. Mutations invalidate summaries and card windows through entity metadata.

Proof: `web/scripts/board-navigation-proof.mjs` (also the grouped-pagination
entry point); backend summary/cursor/permission invariants in
`tests/test_board_loading.py`, `test_item_visibility.py` and
`test_slq_field_oracle.py`. This is incremental loading, not card virtualization:
very deep browsing still accumulates mounted cards.
