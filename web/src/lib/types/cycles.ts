/** Cycles, releases, and dependency links (spec 18). */
import type { StateCategoryValue } from "./workflow";
// ---------------------------------------------------------------------------
// Cycles, releases, dependency links (spec 18)
// ---------------------------------------------------------------------------

/**
 * DERIVED from the cycle's dates (never stored) — mirrors backend `CycleStatus`.
 * `draft` = a dateless staging cycle; never active, off the roadmap (spec 23).
 */
export const CycleStatus = {
  draft: "draft",
  upcoming: "upcoming",
  active: "active",
  completed: "completed",
} as const;
export type CycleStatusValue = (typeof CycleStatus)[keyof typeof CycleStatus];

/** GET /cycles[?status=] — cycles are global, spanning projects (cycle.manage). */
export interface Cycle {
  id: string;
  name: string;
  /** null on a draft (staging) cycle — see spec 23. */
  start_date: string | null;
  end_date: string | null;
  goal: string;
  status: CycleStatusValue;
  /** Set by the explicit "Complete cycle" action. */
  completed_at?: string | null;
  /** Spec 60 visibility: [] = public; non-empty = visible to those teams only. */
  team_ids: string[];
  created_at: string;
  updated_at: string;
}

/** POST /cycles/{id}/complete — the cycle-completion flow. */
export interface CycleComplete {
  /** Where open (not done/canceled) items go — a cycle id, or null = backlog. */
  move_open_to?: string | null;
  /** Give the target cycle dates starting today. */
  start_next?: boolean;
}

export interface CycleCompleteResult {
  cycle: Cycle;
  moved_count: number;
  next_cycle: Cycle | null;
  /** Draft names auto-created to satisfy the `cycle_drafts_ahead` setting. */
  provisioned: string[];
}

export interface CycleCreate {
  name: string;
  /** Omit both (or send null) to create a draft (staging) cycle. */
  start_date?: string | null;
  end_date?: string | null;
  goal?: string;
  /** Register the name's label as a recurring series (auto-provisioned drafts). */
  recurring?: boolean;
  drafts_ahead?: number;
  /** Numbering start for a bare label name (import continuity, e.g. begin at 120). */
  next_number?: number | null;
  /** Cadence (both or neither): 0=Monday … 6=Sunday + duration; provisioned cycles
   * get real timelines chained back-to-back after the label's latest cycle. */
  start_weekday?: number | null;
  duration_days?: number | null;
  /** Spec 60 visibility: omit/[] = public; non-empty = those teams only. */
  team_ids?: string[];
}

/** A recurring cycle label ("PIPE") — membership is by name, config lives here. */
export interface CycleSeries {
  id: string;
  label: string;
  drafts_ahead: number;
  next_number: number;
  start_weekday: number | null;
  duration_days: number | null;
}

export interface CycleSeriesUpdate {
  drafts_ahead?: number;
  next_number?: number;
  /** Explicit null CLEARS the cadence (back to dateless drafts). */
  start_weekday?: number | null;
  duration_days?: number | null;
}

/** GET /cycles/{id}/stats — the cycle page's header metrics. */
export interface CycleStats {
  total: number;
  by_category: Partial<Record<StateCategoryValue, number>>;
  estimate_seconds: number;
  logged_seconds: number;
  remaining_seconds: number;
  estimate: string;
  logged: string;
  remaining: string;
  /** Story points (spec 70): always computed; the UI decides whether to show. */
  points_total: number;
  points_done: number;
}

/** PATCH /cycles/{id} — omitted keys untouched; explicit null clears a date. */
export interface CycleUpdate {
  name?: string;
  start_date?: string | null;
  end_date?: string | null;
  goal?: string;
  /** Spec 60: [] = make public; non-empty = those teams only; omit = unchanged. */
  team_ids?: string[];
}

/** Compact embed of the cycle an item is planned into (status derived). */
export interface CycleRef {
  id: string;
  name: string;
  status: CycleStatusValue;
}

export const ReleaseStatus = {
  planned: "planned",
  released: "released",
} as const;
export type ReleaseStatusValue = (typeof ReleaseStatus)[keyof typeof ReleaseStatus];

/** GET /releases?project_id= — per-project versions (project.manage). */
export interface Release {
  id: string;
  project_id: string;
  name: string;
  version: string;
  status: ReleaseStatusValue;
  released_at: string | null;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface ReleaseCreate {
  project_id: string;
  name: string;
  version: string;
  status?: ReleaseStatusValue;
  description?: string;
}

/** PATCH /releases/{id} — set `status: released` to mark released. */
export interface ReleaseUpdate {
  name?: string;
  version?: string;
  status?: ReleaseStatusValue;
  description?: string;
}

/** Compact embed of the release an item is targeting. */
export interface ReleaseRef {
  id: string;
  version: string;
  status: ReleaseStatusValue;
}

/** Dependency link between two items in the same project. */
export const ItemLinkType = {
  blocks: "blocks",
  relates: "relates",
  duplicates: "duplicates",
  /** Auto-derived from #[…] references in item text (spec 52); not user-addable. */
  mentions: "mentions",
} as const;
export type ItemLinkTypeValue = (typeof ItemLinkType)[keyof typeof ItemLinkType];

/** The item on the far end of a dependency link. */
export interface LinkItem {
  id: string;
  key: string;
  title: string;
}

/** One dependency edge from the perspective of the item being read. */
export interface ItemLink {
  id: string;
  /** The link-type KEY (spec 91: types are data — built-in or custom). */
  link_type: string;
  /** Directional display name for THIS edge (outward if source, inward if target). */
  label: string;
  item: LinkItem;
}

/** An item's dependency links, split by direction (incoming = this item is the target). */
export interface ItemLinks {
  outgoing: ItemLink[];
  incoming: ItemLink[];
}

/** POST /items/{id}/links — address the target by per-project number OR id. */
export interface ItemLinkCreate {
  target_id?: string | null;
  target_number?: number | null;
  link_type: string;
}
