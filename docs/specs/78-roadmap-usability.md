# Spec 78 — Roadmap usability v2: link editing, dependency-aware moves, smart layout

Follow-up to spec 77 from first real use. Four gaps: links can be created but
not broken or retyped in-view; moving a blocker leaves its dependents behind;
the timeline can only grow by dragging a bar to the edge; and "Bring children
into roadmap" stacks naively instead of scheduling. Frontend-heavy + one small
timelogging batch endpoint (per-item estimates for durations).

## 1. Link editing in the view

- **Create with a type**: after the ○-handle drop, a small popover at the drop
  point offers Blocks (default) / Relates / Duplicates; Enter/click applies,
  Esc cancels. POST uses the chosen `link_type`.
- **Connector click**: connectors get pointer events; clicking one opens the
  same popover pre-filled — change type (delete + re-create) or **Remove
  link** (DELETE /items/{id}/links/{link_id}). Gated on item.update.
- **Bar context menu**: a "Dependencies" submenu listing the bar's MANUAL
  links ("blocks DEV-12", "blocked by DEV-3", "relates TD-4") each with
  Remove. (Retype lives on the connector popover.)
- Rendering: `blocks` stays red; `relates`/`duplicates` draw neutral zinc.
  A VIOLATED blocks edge — dependent starts on/before its blocker's end —
  draws dashed amber (the "this ordering is broken" signal).

## 2. Dependency-aware movement (cascade push)

- Committing a move/resize that changes item X's `target_date` finds X's
  `blocks` dependents among the LOADED rows; every dependent Y whose
  `start_date <= X.target_date` is pushed forward so `Y.start =
  X.target + 1d` (duration preserved), recursively for Y's own dependents.
  Push-forward ONLY — moving X earlier just grows slack, nothing pulls back.
- All shifts join the SAME optimistic multi-PATCH unit as the original
  gesture (incl. parent epic auto-stretch for every affected item); one
  rollback + toast on failure; success toast when >0 cascaded:
  "Rescheduled N dependent item(s)".
- Cap: 50 cascaded items (beyond → abort the cascade portion, toast a
  warning, commit only the dragged bar). **Alt-drop skips the cascade**
  (escape hatch, documented in the header hint/tooltip).
- Loaded-rows-only is accepted (SLQ-filtered or unloaded dependents don't
  move; the violation styling in §1 flags them when visible later).

## 3. Timeline extension

- Domain padding becomes BOTH-ended (`ROADMAP_DOMAIN_PAD_DAYS` before the
  min bar too — fixes the spec-77 deviation).
- Axis end caps: a "+1 month" ghost column at EACH end of the header;
  clicking extends the visible domain that direction (session state, additive).
- Drag auto-extend: while a bar/tray ghost is within ~40px of the viewport's
  horizontal edge, auto-scroll AND grow the domain live under the ghost —
  dragging into open future no longer requires pre-stretching.

## 4. Smart layout ("Auto-schedule children")

The epic context-menu verb (replaces naive "Bring children into roadmap";
also offered when all children are already dated — it's a reflow):

- **Inputs** per child: duration = ceil(estimate_seconds / (hours_per_day ×
  3600)) calendar days (min 1) when an estimate exists, else
  `ROADMAP_LEAF_SPAN_DAYS`; assignee id (nullable); `blocks` edges among the
  epic's children.
- **Algorithm** (pure, in roadmap-model.ts, unit-testable):
  1. Topological order over intra-epic `blocks` edges (Kahn); cycles fall
     back to rank order for the remainder.
  2. Walk in topo order: `start = max(anchor, max(blocker.end)+1d,
     sameAssigneeLastEnd+1d)` where anchor = epic.start ?? today. Items with
     DIFFERENT assignees (or no assignee) parallelize freely; items sharing
     an assignee serialize in topo-then-rank order — the user's rule.
  3. `end = start + duration − 1d`. After all children: epic fit-to-children
     patch (outward AND inward — this verb owns the span).
- Applied as ONE optimistic multi-PATCH unit; toast "Scheduled N items".
- **Estimates source**: new `POST /items/timelog/batch {item_ids: [≤200]}`
  (timelogging module, sla/batch shape: readable ids only) →
  `{item_id: {estimate_seconds, logged_seconds}}`; hours/day from the
  existing instance config the SPA already reads. Fetched lazily when the
  roadmap mounts for a project with timelogging enabled (else all-defaults).

## 5. Tests

- Pure model: cascade push (chain, fan-out, cap, no-pull-back), scheduler
  (topo respect, same-assignee serialization, parallel assignees, estimate →
  duration conversion, cycle fallback, anchor rules).  As with 77 there is no
  JS runner — keep every rule in pure functions; server tests cover the new
  batch endpoint (readable filter, shape, cap).

## Known simplifications

- Cascade and scheduling see loaded rows only; violations render amber when
  the data is visible.
- Same-assignee serialization has no working-day calendar (calendar days).
- Retype = delete + create (no PATCH on links — matches the server API).

## As-built notes

**Server** (the spec's one endpoint, no model/migration changes):
`POST /items/timelog/batch {item_ids: [≤200]}` →
`{item_id: {estimate_seconds, logged_seconds}}` in the timelogging module
(`worklog_router.py` → `service.timelog_batch`). Readable-ids filter via
`authz.permissions_for_projects` (the sla/batch idiom) — readable ids ALWAYS
appear (None/0 = "no estimate / nothing logged", never "not allowed"), unknown
and unreadable ids are omitted; compute reuses the spec-76 grouped seams
(`estimate_seconds_by_items`/`logged_seconds_by_items`). Cap is
schema-enforced (`TIMELOG_BATCH_MAX_ITEMS = 200` in `schemas.py`, pydantic
`Field(max_length=…)` → 422). Tests: `tests/test_timelog_batch.py` (shape +
dedupe/unknown-id handling, outsider → `{}`, cap 422) — suite 774 green.

**Link editing** (`LinkPopover.tsx`, new): one popover, two lives. A ○-handle
drop no longer POSTs immediately — `useBarDrag` reports the drop's client
coords, `useRoadmapEditing.beginLink` anchors the popover there (Blocks
highlighted default; Enter = Blocks, Esc cancels, clicking a type POSTs it).
Connectors gained a wide invisible hit path per elbow (`stroke: transparent`,
11px, `pointer-events: stroke` — only rendered when the actor can edit);
clicking opens the same popover pre-filled (`openLinkEditor`): picking another
type retypes via DELETE-then-POST in ONE chain (`mutateAsync` sequence, one
toast on either failure), the red "Remove link" DELETEs (the server accepts
either endpoint's id). The bar context menu gained a **Dependencies** submenu
(both epic and leaf bars): every manual link as "blocks DEV-12" / "blocked by
DEV-3" / "relates TD-4" / "duplicates …/duplicated by …" with per-entry
Remove (mentions skipped); empty → disabled "No links". Connector colors:
blocks red, relates/duplicates zinc-500, violated blocks (pure
`isBlocksViolation`: dependent start <= blocker target, derived-epic endpoints
fall back to `childrenBounds`) dashed amber with the reason in the hover title.

**Cascade** (`cascadePlan` in roadmap-model.ts, wired in
`useRoadmapEditing.commitSpan`): fires only when the commit CHANGES the target
date and Alt was not held at drop (`event.altKey` read at pointerup, documented
in the header Dependencies-toggle tooltip). BFS over `blocks` edges among
loaded rows (adjacency from both link directions), push-forward only:
dependent start <= blocker's effective target → `start = target + 1d`,
duration preserved via `isoDaysBetween`, re-pushes on fan-in take the max
naturally; derived epics are never pushed. Cap
`ROADMAP_CASCADE_MAX_ITEMS = 50` distinct pushes (plus a defensive iteration
guard) → `truncated`: warning toast, only the dragged bar + its own epic
stretch commit. Parent-epic stretches for EVERY moved item are union-deduped
per epic in `epicStretchPatches` (one outward-only patch per epic, epics that
themselves moved are skipped) — spec 77's single-child stretch in `commitSpan`
was REPLACED by this helper so the dragged bar and its cascaded siblings can
never emit two fighting epic patches. Everything joins the one
`useRoadmapItemPatch` unit; success with >0 pushed toasts "Rescheduled N
dependent item(s)".

**Timeline extension**: `buildRoadmapModel` now pads
`ROADMAP_DOMAIN_PAD_DAYS` BEFORE the min bar too (week-snapped; fixes the
spec-77 end-only deviation) and takes additive
`{extendBeforeDays, extendAfterDays}` (`RoadmapExtension`) — session state in
`routes/roadmap.tsx`, reset on project switch,
`ROADMAP_EXTEND_STEP_DAYS = 28` per click so the axis stays Monday-snapped.
Slim "+" caps sit at both ends of the axis header. Drag auto-extend lives in
`useBarDrag`: a rAF loop watches the last pointer position; within
`ROADMAP_EDGE_AUTOSCROLL_PX = 40` of the scroll pane's edge it scrolls
(deltas are scroll-compensated: `dx + (scrollLeft − originScrollLeft)`), and
once the pane is pinned at an end it calls `onAutoExtend` (throttled ~600ms).
A before-extension moves the domain start, so `RoadmapTimeline` detects the
`domainStart` shift in a `useLayoutEffect` and calls `drag.shiftDomain(k)` —
the live drag's row indices shift +k and the ghost stays on the same calendar
dates while new weeks open under the pointer.

**Auto-schedule** (`autoSchedulePlan` + `intraEpicBlocksEdges` +
`durationDaysFromEstimate`, all pure): replaces "Bring children into roadmap"
(`bringChildrenPlan` deleted; `RoadmapRow.datelessChildren` became
`children` = ALL loaded children in rank order — the API's default rank-ASC
list order IS the rank tiebreak). Kahn via repeated rank-ordered sweeps
(deterministic topo-then-rank), cyclic remainder appended in rank order with
unplaced blockers simply ignored; walk sets
`start = max(anchor, blockersEnd+1d, sameAssigneeLastEnd+1d)`,
`end = start + duration − 1`; the epic fit patch (inward AND outward) is
appended last. Durations: the roadmap lazily POSTs the batch for every epic's
loaded children when `projectTimeloggingQuery` says enabled (and the actor can
edit); `retry: false` + no error toast — 404/409/disabled all degrade to
`ROADMAP_LEAF_SPAN_DAYS`; hours/day from `useDurationConfig` (GET /instance).
Applied as one optimistic unit; toast "Scheduled N items". The verb is
enabled whenever ANY children are loaded (it's a reflow), with the
estimates/dependencies/assignee rules explained in its hint.

**Deviations from the letter of the spec/plan**: `cascadePlan` returns
`{patches: [{itemId, patch}], cascadedCount, truncated}` — patch objects
rather than flat `{itemId, start_date, target_date}` triples, because the
riding epic stretches may set only one date; `autoSchedulePlan` takes the
`epic` Item as an explicit fifth argument (the fit patch needs its id); tray
(HTML5) drags don't auto-extend — only pointer-event bar drags do; the "+1
month" caps are 28 days, keeping week alignment. No JS test runner exists (as
in 77): every new rule is a pure exported function in `roadmap-model.ts` and
`tsc -b` + `vite build` are the frontend check.
