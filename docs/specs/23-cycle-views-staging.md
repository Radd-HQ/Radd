# Spec 23 — Cycle as a view axis + staging (draft) cycles

**Goal.** Let a saved view group by **Cycle** — every workspace cycle becomes a
collapsible section/column with a summary (status · dates · progress), items
with no cycle collect under **Backlog**, and an optional per-view **cycle-name
filter** narrows the header set (e.g. `PIPE - *`). Add **draft/staging cycles**:
a cycle with no dates is a placeholder bucket you plan work into, never "active",
excluded from roadmap/velocity/burnup — give it dates later to schedule it.

Builds on spec 14 (cycles/planning), spec 10 (SLQ + views), spec 11 (swimlanes).

## 1. Draft cycles (nullable dates → derived `DRAFT`)

`cycles.start_date` / `end_date` become **nullable**. Status stays DERIVED — no
new stored column:

```
cycle_status(start, end, today):
  start is None or end is None -> DRAFT      # a staging area; never active
  today < start                -> UPCOMING
  today > end                  -> COMPLETED
  else                         -> ACTIVE
```

`CycleStatus` gains `DRAFT` (listed first). Contract:

- `CycleCreate.start_date` / `end_date` are optional (`date | None = None`). Name
  is still required. `CycleUpdate` uses the `model_fields_set` idiom so an
  explicit `null` **clears** a date (scheduled → draft); omitted = unchanged.
- `_check_dates` only fires when **both** dates are present (`end >= start`).
- `CycleRead.start_date` / `end_date` are nullable; `cycle.updated`/`cycle.created`
  event payloads carry `null` for an absent date.
- `active_cycles` is unchanged: its `start <= today <= end` predicate never
  matches NULL columns, so a draft cycle is correctly never "active".

**Reporting guard.** `velocity` already filters to `COMPLETED` cycles (which
always have dates), so it is unaffected. `burnup(cycle_id)` needs a window →
raises `ConflictError` (409) for an undated (draft) cycle rather than iterating a
`None` range.

## 2. Cycle as a view axis + per-view cycle filter

- `ViewAxis` gains `CYCLE = "cycle"` — a builtin axis, so `AXIS_TOKEN_PATTERN`
  and `_validate_axes` accept it with no extra rules (usable for `group_by` and
  `swimlane_by`). SLQ's `cycle` field is unchanged (item filtering is separate).
- `views` gains a nullable `cycle_filter` TEXT column: an optional cycle-name
  glob applied to the **header set** when an axis is `cycle`. Blank/absent = all
  cycles. `ViewCreate.cycle_filter` (≤200 chars), `ViewUpdate.cycle_filter`
  (`model_fields_set` clear), `ViewRead.cycle_filter`. Not validated server-side
  (a display glob, matched client-side); stored verbatim.

## 3. Frontend — grouping, summary, collapse, staging

**Bucketing (`lib/view-utils.ts`).** `AxisContext` gains `cycles?: Cycle[]` and
`cycleFilter?: string | null`. `groupByCycle`:

- Buckets come from the **full workspace cycle list** (so empty staging cycles
  appear), filtered by `cycleFilter` (case-insensitive glob: `*`/`?` wildcards,
  otherwise a substring contains — `PIPE - *` and `PIPE` both match `PIPE - 116`).
- Order: **active → upcoming → draft → completed** (`CYCLE_STATUS_ORDER`), then by
  `start_date` (drafts, dateless, by name). A **Backlog** bucket (no-cycle items)
  is always present and rendered **last**.
- Each cycle bucket carries `detail` = `"Active · Aug 1 – Aug 14 · 3/8 done"` (draft:
  `"Draft · Not scheduled · 0/2 done"`) and `progress` = done/total for a thin bar;
  `dotClassName` = the status dot.
- Items whose cycle is **not** in the (filtered) header set are omitted — that is
  what the pattern filter means; with no filter every cycle shows, so nothing is
  dropped. The view header shows the **sum of bucketed items** (correct for every
  axis; only differs from the SLQ total when a cycle filter hides cycles).

`ViewGroup` gains optional `detail?: string` and `progress?: number` (0–1).

**Rendering.** `ViewList` sections become **collapsible** (chevron header, count,
`detail` sub-line + progress bar), collapsed set persisted per view in
localStorage (`listSectionCollapseStorageKey`, mirroring swimlanes). `ViewBoard`
columns show the same `detail` + progress bar under the header (no column
collapse). `view.tsx` fetches `cyclesQuery(workspace.id)`, feeds
`cycles`/`view.cycle_filter` into `AxisContext`, passes `viewId` to `ViewList`,
and shows the summed count.

**Builder (`ViewModal`).** `Cycle` appears in the Columns/Swimlanes pickers
(via `VIEW_AXIS_ORDER`). A **Cycle filter** text input shows only when an axis is
`cycle`; its value saves as `cycle_filter`.

**Settings (`settings/cycles.tsx`).** Dates are optional: a cycle created with no
dates is a **draft (staging)** cycle. The modal requires *both-or-neither* date
(one alone is rejected client-side); the row/badge show `Draft` + "Not scheduled".
`cycle.tsx` renders "Not scheduled" for a dateless cycle. `CYCLE_STATUS_META`
gains a `draft` entry.

## 4. Non-goals / simplifications

- No SLQ `cycle ~` operator — the pattern filter is a display concern on headers,
  not an item filter (empty staging cycles have no items to match).
- `cycle_filter` is stored on every view but only consumed when an axis is
  `cycle`; it is not glob-validated server-side.
- Completed cycles still show by default (ordered last, collapsible) — no
  auto-hide.
- `ViewBoard` columns are not collapsible (only `ViewList` sections are); the
  ad-hoc project **list** route (`/p/$key/list`, a flat table) is unchanged —
  cycle grouping is a saved-view feature.
- A cycle with exactly one date is allowed by the backend (→ DRAFT) but the
  settings modal steers you to both-or-neither.
