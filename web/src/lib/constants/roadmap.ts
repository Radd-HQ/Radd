/** Roadmap/Gantt layout + interaction constants (specs 77/78). */

/** Minimum pixel width per day column on the roadmap time axis (drives horizontal scroll). */
export const ROADMAP_DAY_WIDTH = 9;
/** Fixed width of the roadmap's left label gutter (item rows + axis spacer align to it). */
/** Default width of the roadmap's row-label gutter. Resizable at runtime
 *  (persisted per view) — read the LIVE value from props, never this constant,
 *  anywhere geometry depends on it: it feeds pointer→day hit-testing, so a
 *  stale value silently drops bars on the wrong date. */
export const ROADMAP_LABEL_WIDTH = 260;
/** Resize clamps: below the min the keys stop fitting, above the max the
 *  timeline stops being the point of the screen. */
export const ROADMAP_LABEL_MIN_WIDTH = 120;
export const ROADMAP_LABEL_MAX_WIDTH = 560;

/** Roadmap zoom levels (spec 77): selectable day widths for the time axis. */
export const ROADMAP_ZOOM_LEVELS: readonly { width: number; label: string }[] = [
  { width: 6, label: "Compact" },
  { width: ROADMAP_DAY_WIDTH, label: "Default" },
  { width: 14, label: "Wide" },
];
/** Continuous zoom bounds (viewport wave): ctrl+wheel / ± buttons move the
 *  day width anywhere in this range; the presets above are just landmarks. */
export const ROADMAP_DAY_WIDTH_MIN = 2;
export const ROADMAP_DAY_WIDTH_MAX = 40;
/** One ctrl+wheel notch (deltaY 100) multiplies the day width by this. */
export const ROADMAP_ZOOM_WHEEL_FACTOR = 1.18;
/** Rubber-band drags shorter than this (px) count as plain clicks. */
export const ROADMAP_BAND_THRESHOLD_PX = 4;
/** Frame-selected (F): the selection span fills this fraction of the pane. */
export const ROADMAP_FRAME_FILL = 0.8;

/**
 * Default bar length when an unscheduled item is dragged onto the roadmap
 * (spec 77): start = the drop day, target = start + N days (inclusive spans —
 * 6 extra days = a one-week bar, 20 = about three weeks). The leaf span also
 * paces "Bring children into roadmap" (each child gets a week-long bar).
 */
export const ROADMAP_LEAF_SPAN_DAYS = 6;
export const ROADMAP_EPIC_SPAN_DAYS = 20;

/** One click/hold of a "+1 month" timeline extension (spec 78) — kept a whole
 *  number of weeks so the axis stays Monday-snapped. */
export const ROADMAP_EXTEND_STEP_DAYS = 28;
/** Drag ghosts within this many px of the scroll pane's edge auto-scroll (spec 78). */
export const ROADMAP_EDGE_AUTOSCROLL_PX = 40;
/** Dependency-cascade cap (spec 78): more pushed items than this aborts the
 *  cascade portion — only the dragged bar commits. */
export const ROADMAP_CASCADE_MAX_ITEMS = 50;
/** Hover dwell before a roadmap bar shows its floating info card. */
export const ROADMAP_HOVER_CARD_DELAY_MS = 350;
/** Staleness for the roadmap's progress-tint batches (timelog + rollup) —
 *  roadmaps can be huge, so refetch rarely; item mutations still invalidate
 *  through the query meta. No polling. */
export const ROADMAP_PROGRESS_STALE_MS = 5 * 60_000;

/**
 * Scale guardrails (perf wave): a roadmap only ever draws epics
 * and dated bars, so the fetch narrows to exactly that instead of streaming
 * the whole match set — on a 100k-item project that is the difference between
 * 505 sequential pages (~200 MB) and ~10. Unscheduled leaves come from the
 * tray's own bounded query; an epic's date-less children are fetched only
 * when a verb needs them (`parent = KEY`).
 */
export const ROADMAP_STRUCTURE_QUERY =
  "kind = epic OR (start IS NOT EMPTY AND target IS NOT EMPTY)";
/** The "Epics only" toggle: epics + their scheduled DIRECT children, nothing
 *  else. `kind = issue AND epic IS NOT EMPTY` is exactly "direct epic child"
 *  (an issue's parent can only be an epic), so epicless leaves and subtasks
 *  drown out — the quick de-noise filter for epic-driven planning. */
export const ROADMAP_EPICS_ONLY_QUERY =
  "kind = epic OR (kind = issue AND epic IS NOT EMPTY AND " +
  "start IS NOT EMPTY AND target IS NOT EMPTY)";
/** Default-on recency policy ("Show closed" toggles it off): closed items
 *  keep drawing while their bar ended within ~3 months, then drop out. */
export const ROADMAP_RECENT_CLOSED_QUERY =
  "category NOT IN (done, canceled) OR target >= today-12w";
/** The tray pool: open items missing a full start+target window. Epics with
 *  a derived (children-union) bar are deduped out client-side. */
export const ROADMAP_TRAY_QUERY =
  "(start IS EMPTY OR target IS EMPTY) AND category NOT IN (done, canceled)";
/** Auto-stream this many pages per burst, then pause with a notice — "Load
 *  more" arms another burst. Keeps a broad query from re-creating fetch-all. */
export const ROADMAP_MAX_AUTO_PAGES = 15;
/** Tray page size — a scan-and-drag pool, not a list view. */
export const ROADMAP_TRAY_PAGE_LIMIT = 50;
/** On-demand children fetch cap (auto-schedule / bring-into-roadmap): pages
 *  of ITEMS_PAGE_LIMIT — an epic with more than ~2000 children is malformed. */
export const ROADMAP_CHILDREN_PAGE_CAP = 10;
/** Curated-membership read cap — the items endpoint's page maximum (le=200);
 *  a hand-picked roadmap past this is a filter problem, not a pinning one. */
export const ROADMAP_MEMBERS_LIMIT = 200;
