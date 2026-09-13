/**
 * Pure layout + interaction model for the roadmap/Gantt (specs 19 + 77 + 78 +
 * 82): turns a project's items into ordered, date-positioned rows over a
 * week-snapped time domain (plus the "unscheduled" leftovers), and hosts ALL
 * the date math the editing gestures need — px↔day conversion, span
 * move/resize clamping, the parent-epic outward-stretch union, fit-to-children,
 * the dependency cascade planner, and the estimate/assignee-aware
 * auto-scheduler. Row order is STABLE (spec 82): the fetch order — global
 * manual rank by default — is the row order; date edits only move bars
 * horizontally. No React here — just dates and folds, so `tsc` plus reading
 * is the whole test story.
 *
 * Intentional re-export barrel — the implementation now lives in ./model/*
 * (dates / geometry / rows / planning / scheduling / reorder / progress); the
 * named re-export list for ./model/dates deliberately omits its three
 * module-internal helpers (toIsoDay / addDays / startOfWeek).
 */
export {
  ROADMAP_DOMAIN_PAD_DAYS,
  parseDay,
  shiftIso,
  daysBetween,
  isoDaysBetween,
  isoFromDay,
  isScheduled,
} from "./model/dates";
export * from "./model/geometry";
export * from "./model/rows";
export * from "./model/planning";
export * from "./model/scheduling";
export * from "./model/reorder";
export * from "./model/progress";
