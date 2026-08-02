/** localStorage keys for persisted UI prefs (tree/sidebar/swimlane/section/roadmap collapse state). */

/** localStorage key for a page space's expanded tree node ids (JSON string[]). */
export const pageTreeExpandStorageKey = (spaceId: string) => `radd.docs.${spaceId}.expanded`;

/** localStorage key for a view's collapsed swimlane bucket keys (JSON string[]). */
export const swimlaneCollapseStorageKey = (viewId: string) =>
  `radd.view.${viewId}.collapsed-lanes`;

/** localStorage key for a list view's collapsed section keys (JSON string[], spec 23). */
/** Per-surface card display config (slots/labels/scale) — see lib/card-display.ts. */
export const cardDisplayStorageKey = (surfaceKey: string) => `radd.cardDisplay.${surfaceKey}`;

/** Sidebar collapse prefs (spec 60): collapsed sections + expanded/collapsed projects. */
export const SIDEBAR_PREFS_STORAGE_KEY = "radd.sidebar";

export const listSectionCollapseStorageKey = (viewId: string) =>
  `radd.view.${viewId}.collapsed-sections`;

/** Per-user column widths on a list view (spec 108) — {columnId: px}. The
 * column SET lives on the saved view; widths are personal ergonomics. The key
 * contains the view id, so "Reset view" sweeps it automatically. */
export const viewColumnWidthsStorageKey = (viewId: string) =>
  `radd.view.${viewId}.column-widths`;

/** localStorage key for a roadmap view's collapsed epic ids (JSON string[],
 * spec 77 — VIEW-scoped since roadmaps became saved views, spec 79). */
export const roadmapCollapseStorageKey = (viewId: string) =>
  `radd.roadmap.${viewId}.collapsed-epics`;

/** localStorage key for a roadmap view's Unscheduled-tray filter chip
 * (spec 79: "all" | "epics", persisted per view). */
export const roadmapTrayFilterStorageKey = (viewId: string) =>
  `radd.roadmap.${viewId}.tray-filter`;

/** Collapse state for a docked side panel (roadmap tray, issue rail, …). */
export const sidePanelStorageKey = (panelKey: string) => `radd.panel.${panelKey}`;

/** Roadmap label-gutter width, dragged by the divider (spec 79 follow-up). */
export const roadmapLabelWidthStorageKey = (viewId: string) =>
  `radd.roadmap.${viewId}.labelWidth`;

/** Roadmap "Show closed" toggle (perf wave): off = the default recency filter
 *  (closed items drop out ~3 months after their bar ends) applies. */
export const roadmapShowClosedStorageKey = (viewId: string) =>
  `radd.roadmap.${viewId}.showClosed`;

/** Roadmap "Epics only" toggle: on = only epics + their scheduled children
 *  draw (standalone leaves drown out). Per view, like Show closed. */
export const roadmapEpicsOnlyStorageKey = (viewId: string) =>
  `radd.roadmap.${viewId}.epicsOnly`;

/** Roadmap Members/All toggle OVERRIDE ("1"/"0"; unset = derive: members-only
 *  whenever the view has members). Per view. */
export const roadmapMembersOnlyStorageKey = (viewId: string) =>
  `radd.roadmap.${viewId}.membersOnly`;

/** Peek drawer width (one drawer app-wide, so not keyed per view). */
export const PEEK_WIDTH_STORAGE_KEY = "radd.peek.width";
