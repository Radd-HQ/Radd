/** Approvals on workflow transitions (spec 71). */
// ---------------------------------------------------------------------------
// Approvals on workflow transitions (approvals module — spec 71)
// ---------------------------------------------------------------------------

export const ApprovalStatus = {
  pending: "pending",
  approved: "approved",
  declined: "declined",
  canceled: "canceled",
  applied: "applied",
} as const;
export type ApprovalStatusValue = (typeof ApprovalStatus)[keyof typeof ApprovalStatus];

export const ApprovalVerdict = {
  approve: "approve",
  decline: "decline",
} as const;
export type ApprovalVerdictValue = (typeof ApprovalVerdict)[keyof typeof ApprovalVerdict];

export interface ApprovalUserRef {
  id: string;
  name: string;
}

export interface ApprovalVote {
  user: ApprovalUserRef;
  verdict: ApprovalVerdictValue;
  note: string;
  created_at: string;
}

/** Per-entry progress (spec 107): a user entry needs that person's approval;
 * a team entry needs `required` approvals from its CURRENT members. */
export interface ApprovalEntry {
  kind: "user" | "team";
  id: string;
  name: string;
  required: number;
  approved_count: number;
  satisfied: boolean;
}

export interface ApprovalRequest {
  id: string;
  item_id: string;
  to_state_id: string;
  to_state_name: string;
  status: ApprovalStatusValue;
  note: string;
  requested_by: ApprovalUserRef | null;
  /** Per-entry rules + progress — the card's primary display (spec 107). */
  entries: ApprovalEntry[];
  /** The CURRENT electorate (entry users ∪ live team members), server-resolved. */
  approvers: ApprovalUserRef[];
  approved_count: number;
  votes: ApprovalVote[];
  created_at: string;
}

/** GET /items/{id}/approvals — the issue rail's Approvals card source. */
export interface ItemApprovals {
  live: ApprovalRequest[];
  history: ApprovalRequest[];
  /** Approval-gated targets from the CURRENT state with no live request yet. */
  requestable_to_states: { state_id: string; name: string }[];
}

/** POST /approvals/{id}/vote — `errors` = banked-unlock guard failures to toast. */
export interface ApprovalVoteResult {
  request: ApprovalRequest;
  applied: boolean;
  errors: string[];
}

/** One row of GET /approvals/pending — the My Work "Awaiting my approval" card. */
export interface PendingApproval {
  id: string;
  item_id: string;
  item_key: string;
  item_title: string;
  to_state_name: string;
  requested_by: ApprovalUserRef | null;
  note: string;
  created_at: string;
}
