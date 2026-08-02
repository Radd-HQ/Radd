/** Saved views + sharing (specs 08/10/57). */
// ---------------------------------------------------------------------------
// Saved views (spec 08, reworked to SLQ + swimlanes by spec 10)
// ---------------------------------------------------------------------------

export const ViewType = {
  board: "board",
  list: "list",
  /** Backlog & cycle planning: cycle-grouped sections with cross-bucket drag. */
  planning: "planning",
  /** Triage queue (spec 64): fixed-column list — reporter, age, always-on SLA
   *  chips, urgency-ordered; axes ignored like planning. */
  queue: "queue",
  /** Roadmap/Gantt (spec 79): the timeline as a saved view — axes ignored;
   *  the page auto-fetches EVERY page of the view query (no Load-more). */
  roadmap: "roadmap",
} as const;
export type ViewTypeValue = (typeof ViewType)[keyof typeof ViewType];

/** Builtin grouping axes for a view (board columns / list sections / swimlanes). */
export const ViewAxis = {
  state: "state",
  assignee: "assignee",
  priority: "priority",
  kind: "kind",
  team: "team",
  cycle: "cycle",
} as const;
export type ViewAxisValue = (typeof ViewAxis)[keyof typeof ViewAxis];

/** Axis-token prefix for select-type custom fields (spec 10: `cf.<key>`). */
export const CF_AXIS_PREFIX = "cf.";

/**
 * `group_by`/`swimlane_by` domain (spec 10): a builtin axis or `cf.<key>`
 * where `<key>` is a SELECT-type registry field in the view's scope.
 */
export type AxisToken = ViewAxisValue | `${typeof CF_AXIS_PREFIX}${string}`;

/** One clickable filter chip on a view — conditions-only SLQ, AND-ed when active. */
export interface QuickFilter {
  name: string;
  query: string;
}

/** GET /views (spec 10). `project_id` null = all-projects; `owner_id` null = shared. */
/** Access a share grant (or the everyone-on-this-server grant) confers
 *  (spec 57). `owner` = co-ownership (edit + re-share + delete + transfer);
 *  never valid for the server-wide grant. */
export const ShareLevel = {
  viewer: "viewer",
  editor: "editor",
  owner: "owner",
} as const;
export type ShareLevelValue = (typeof ShareLevel)[keyof typeof ShareLevel];

export interface ShareSubjectRef {
  id: string;
  name: string;
}

/** One sharing grant on a view — exactly one of user/team is set. */
export interface ViewShare {
  id: string;
  level: ShareLevelValue;
  user: ShareSubjectRef | null;
  team: ShareSubjectRef | null;
}

/** PUT /views/{id}/sharing — the FULL sharing state, replaced atomically.
 * `global_access` means "everyone on this server" (spec 86). */
export interface ViewSharingUpdate {
  // Spec 92: the public level only; per-subject shares are access grants now.
  global_access: ShareLevelValue | null;
}

/** One placed card attribute (spec 109): `title`, a builtin column id, or
 * `cf.<key>`. Row 0 is the header lane; `align: "end"` packs right. */
export interface CardLayoutCell {
  attr: string;
  row: number;
  col: number;
  span: number;
  align?: "start" | "end";
}

/** The board-card layout (spec 109) — an 8-column grid rendered as flex
 * lanes. Stored on the view (`null` = the default card) and in presets. */
export interface CardLayout {
  v: 1;
  cells: CardLayoutCell[];
  /** Label chips before the "+N" overflow — shared (part of the design). */
  max_labels: number;
}

/** A named layout in the shared instance library (spec 109). Applying one
 * COPIES its layout onto the view — a snapshot, never a live reference. */
export interface CardLayoutPreset {
  id: string;
  name: string;
  layout: CardLayout;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface View {
  id: string;
  project_id: string | null;
  name: string;
  view_type: ViewTypeValue;
  /** SLQ query text (spec 10 grammar); empty = match everything in scope. */
  query: string;
  group_by: AxisToken | null;
  /** Swimlane axis (boards); must differ from `group_by`. */
  swimlane_by: AxisToken | null;
  /** Cycle-name regex for the `cycle` axis header set (specs 23/56); null = all. */
  cycle_filter: string | null;
  /** Jira-style clickable filter chips; active ones AND into the query. */
  quick_filters: QuickFilter[];
  /** Soft WIP limits (spec 76): {state_id: n>=1} shown on state-axis board
   * column headers (n/limit, amber at, red above); null = none. */
  wip_limits?: Record<string, number> | null;
  /** Ordered LIST-surface column ids (builtin names or `cf.<key>`, spec 108);
   * null = the view type's default set. Widths are per-user, not here. */
  columns?: string[] | null;
  /** Board-card layout (spec 109); null = the type's default card. */
  card_layout?: CardLayout | null;
  owner_id: string | null;
  /** Sharing (spec 57): the owner, the server-wide grant, explicit grants.
   * `global_access` = the wire name for "everyone on this server". */
  owner: ShareSubjectRef | null;
  global_access: ShareLevelValue | null;
  shares: ViewShare[];
  /** Visible beyond the owner (server-wide, grants, or legacy owner-less). */
  shared: boolean;
  /** Per-actor capabilities, computed server-side. */
  can_edit: boolean;
  can_manage: boolean;
  position: number;
  /** Pre-composed `GET /items?…` query (`q=…` + scope) — append verbatim. */
  query_string: string;
  created_at: string;
  updated_at: string;
}

export interface ViewCreate {
  project_id?: string | null;
  name: string;
  view_type: ViewTypeValue;
  query?: string;
  group_by?: AxisToken | null;
  swimlane_by?: AxisToken | null;
  cycle_filter?: string | null;
  quick_filters?: QuickFilter[];
  /** Wire name for "everyone on this server" (spec 86). */
  global_access?: ShareLevelValue | null;
  shares?: { user_id?: string; team_id?: string; level: ShareLevelValue }[];
}

/** PATCH /views/{id} — explicit `null` clears an axis. */
export interface ViewUpdate {
  name?: string;
  view_type?: ViewTypeValue;
  query?: string;
  group_by?: AxisToken | null;
  swimlane_by?: AxisToken | null;
  cycle_filter?: string | null;
  quick_filters?: QuickFilter[];
  /** Soft WIP limits (spec 76); explicit null clears them all. */
  wip_limits?: Record<string, number> | null;
  /** List columns (spec 108); explicit null = back to the type's defaults. */
  columns?: string[] | null;
  /** Card layout (spec 109); explicit null = back to the type's default card. */
  card_layout?: CardLayout | null;
}
