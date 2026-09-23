/** Work items, issue types, participants, and bulk operations (specs 02/51/68/72). */
import type { CycleRef, ItemLinks, ReleaseRef } from "./cycles";
import type { StateRef } from "./workflow";
// ---------------------------------------------------------------------------
// Request participants (participants module — spec 72)
// ---------------------------------------------------------------------------

/** One grant row of GET /items/{id}/participants — the id addresses DELETE. */
export interface ParticipantRow {
  id: string;
  user: UserRef | null;
  team: TeamRef | null;
  added_by: UserRef | null;
  created_at: string;
}

/** Issue type (spec 51): the per-project classification axis (Bug/Task/Story/…). */
export interface IssueType {
  id: string;
  project_id: string;
  name: string;
  color: string; // "#rrggbb"
  icon: string | null; // lucide key
  position: number;
  is_default: boolean;
  /** Issue template (spec 76): markdown prefilled into a pristine new-item
   * description when this type is selected; null = no template. */
  description_template?: string | null;
}

/** Embedded issue-type reference on an item. */
export interface TypeRef {
  id: string;
  name: string;
  color: string;
  icon: string | null;
}

// ---------------------------------------------------------------------------
// Items (specs — 02 contract frozen; kind/parent/assignee/team/counts may be
// absent from responses until the Wave 2 backend lands, hence optional)
// ---------------------------------------------------------------------------

export const Priority = {
  low: "low",
  normal: "normal",
  high: "high",
  blocker: "blocker",
} as const;
export type PriorityValue = (typeof Priority)[keyof typeof Priority];

/** Spec 121: who may read an issue beyond holding item.read on its project. */
export const ItemVisibility = {
  public: "public",
  internal: "internal",
  restricted: "restricted",
} as const;
export type ItemVisibilityValue = (typeof ItemVisibility)[keyof typeof ItemVisibility];

export const ItemKind = {
  epic: "epic",
  issue: "issue",
  subtask: "subtask",
} as const;
export type ItemKindValue = (typeof ItemKind)[keyof typeof ItemKind];

/** A custom-field value as validated by the fields registry; null clears. */
export type CustomFieldValue = string | number | boolean | string[] | null;
export type CustomFields = Record<string, CustomFieldValue>;

export interface ItemParentRef {
  id: string;
  key: string;
  title: string;
}

/** Embedded people refs on ItemRead / comments / worklogs (spec 02 + 34). */
export interface UserRef {
  id: string;
  name: string;
  /** Avatar (spec 34): colored initials circle, optional emoji override. */
  avatar_color?: string | null;
  avatar_emoji?: string | null;
  avatar_url?: string | null;
}

export interface TeamRef {
  id: string;
  name: string;
}

/** The ACTOR's per-row verdict (RADD-842) — writability is per-ROW once
 * relations exist (`item.update@own`). Absent = fall back to project-level. */
export interface ItemCapabilities {
  can_update: boolean;
  can_transition: boolean;
  can_comment: boolean;
}

export interface Item {
  id: string;
  project_id: string;
  key: string;
  number: number;
  /** RADD-842: per-row writability; null/absent on payloads with no actor. */
  capabilities?: ItemCapabilities | null;
  title: string;
  description: string;
  state: StateRef;
  priority: PriorityValue;
  labels: string[];
  custom_fields: CustomFields;
  created_at: string;
  updated_at: string;
  // Spec-02 additions — optional until the backend wave lands:
  kind?: ItemKindValue;
  type?: TypeRef | null; // spec 51 — issue-type classification
  parent?: ItemParentRef | null;
  /** The epic this item BELONGS TO — itself if it is one, else its parent, else
   *  its grandparent (RADD-697, server-resolved: the client cannot see two hops
   *  up). Null for work no epic governs. Drives the `epic` view axis. */
  epic?: ItemParentRef | null;
  assignee?: UserRef | null;
  /** Who raised the issue (service-desk requester, spec 30) — defaults to creator. */
  reporter?: UserRef | null;
  team?: TeamRef | null;
  child_count?: number;
  comment_count?: number;
  // Spec-18 planning fields (cycles, releases, dates, dependency links):
  start_date?: string | null;
  target_date?: string | null;
  cycle?: CycleRef | null;
  /** Cycles the item was previously in (spec 56, oldest-first) — the carryover
   *  trail; queryable as SLQ `past_cycle`. */
  past_cycles?: CycleRef[];
  release?: ReleaseRef | null;
  /** First-class shared flag (spec 24) — a core boolean, not a label. */
  flagged?: boolean;
  /** Spec 121: public | internal | restricted. */
  visibility?: ItemVisibilityValue;
  /** Story points (spec 70) — null/absent = unestimated; UI gated per project. */
  estimate_points?: number | null;
  /** Soft-archived timestamp (spec 38) — hidden from lists by default. */
  archived_at?: string | null;
  /** Personal star for the requesting user (spec 24). */
  starred?: boolean;
  /** Dependency edges from this item's perspective; absent → treat as empty. */
  links?: ItemLinks;
}

export interface ItemCreate {
  project_id: string;
  title: string;
  description?: string;
  state_id?: string;
  priority?: PriorityValue;
  labels?: string[];
  custom_fields?: CustomFields;
  // Spec-02 additions (ignored by the backend until it lands):
  kind?: ItemKindValue;
  type_id?: string | null; // spec 51 — null/omitted on create = project default
  parent_id?: string | null;
  assignee_id?: string | null;
  reporter_id?: string | null;
  team_id?: string | null;
  // Spec-18 planning fields (null clears):
  start_date?: string | null;
  target_date?: string | null;
  cycle_id?: string | null;
  release_id?: string | null;
  flagged?: boolean;
  /** Spec 121: omitted = the project's default visibility. */
  visibility?: ItemVisibilityValue;
  /** Story points (spec 70): 0–999, one decimal. */
  estimate_points?: number | null;
}

/** PATCH /items/{id} — omitted keys untouched; explicit null clears (spec 02). */
export interface ItemUpdate {
  title?: string;
  description?: string;
  state_id?: string;
  priority?: PriorityValue;
  labels?: string[];
  custom_fields?: CustomFields;
  type_id?: string | null; // spec 51 — null clears the type
  parent_id?: string | null;
  assignee_id?: string | null;
  reporter_id?: string | null;
  team_id?: string | null;
  // Spec-18 planning fields — omitted keys untouched; explicit null clears.
  start_date?: string | null;
  target_date?: string | null;
  cycle_id?: string | null;
  release_id?: string | null;
  flagged?: boolean;
  /** Spec 121: omitted = unchanged. */
  visibility?: ItemVisibilityValue;
  /** Story points (spec 70) — omitted = unchanged; explicit null clears. */
  estimate_points?: number | null;
}

// ---------------------------------------------------------------------------
// Bulk operations (spec 68)
// ---------------------------------------------------------------------------

/** POST /items/bulk-update `patch` — the restricted bulk-editable subset;
 *  labels are DELTAS (add/remove), archived rides along as a boolean. */
export interface ItemBulkPatch {
  state_id?: string;
  assignee_id?: string | null;
  team_id?: string | null;
  priority?: PriorityValue;
  type_id?: string | null;
  cycle_id?: string | null;
  release_id?: string | null;
  flagged?: boolean;
  archived?: boolean;
  add_labels?: string[];
  remove_labels?: string[];
}

export const BulkSkipReason = {
  notFound: "not_found",
  forbidden: "forbidden",
  invalidTarget: "invalid_target",
  transitionBlocked: "transition_blocked",
  error: "error",
} as const;
export type BulkSkipReasonValue = (typeof BulkSkipReason)[keyof typeof BulkSkipReason];

export interface BulkSkipped {
  item_id: string;
  key: string | null;
  reason: BulkSkipReasonValue;
  detail: string | null;
}

export interface BulkUpdateResult {
  updated: string[];
  skipped: BulkSkipped[];
}

export interface BulkMovedItem {
  item_id: string;
  old_key: string;
  new_key: string;
  dropped_fields: string[];
}

export interface BulkMoveResult {
  moved: BulkMovedItem[];
  skipped: BulkSkipped[];
}

/** GET /items/ids — ids capped server-side, total = true visible count. */
export interface ItemIds {
  ids: string[];
  total: number;
}
