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
