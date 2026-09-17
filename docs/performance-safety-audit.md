# Performance changes: functionality audit

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

## Implemented outcome (2026-09-17)

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
