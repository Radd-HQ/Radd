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
  /** RADD-1291: the home project (who plans it); null = an instance cycle. */
  project_id?: string | null;
  created_at: string;
  updated_at: string;
}

