/** Time logging + timesheets (spec 22). */
import type { UserRef } from "./items";
// ---------------------------------------------------------------------------
// Time logging + timesheets (spec 22)
// ---------------------------------------------------------------------------

interface CategoryRef {
  id: string;
  name: string;
}

interface ItemRef {
  id: string;
  key: string;
  title: string;
  project_key: string;
}

/** GET/PUT /projects/{id}/timelogging — per-project enablement. */
export interface ProjectTimeLogging {
  project_id: string;
  enabled: boolean;
}

/** GET /work-categories — the server-wide worklog category list. */
export interface WorkCategory {
  id: string;
  name: string;
  position: number;
  archived: boolean;
}

export interface WorkCategoryCreate {
  name: string;
}

export interface WorkCategoryUpdate {
  name?: string;
  archived?: boolean;
}

/** A logged-work entry (GET /items/{id}/timelog embeds these). */
export interface Worklog {
  id: string;
  item_id: string;
  author: UserRef;
  category: CategoryRef | null;
  worked_on: string; // YYYY-MM-DD
  time_spent_seconds: number;
  time_spent: string; // server-formatted, e.g. "1h 30m"
  note: string;
  /** RADD-1258: "" = logged in Radd; a VcsProvider value = mirrored from time
   *  logged on a merge/pull request there. Mirrored rows are read-only here. */
  external_source: string;
  /** The ref's external id (`pr:<repo>:<n>`) when mirrored, else "". */
  external_scope: string;
  created_at: string;
  updated_at: string;
}

/** POST /items/{id}/worklogs — `time_spent` is Jira-style duration text. */
export interface WorklogCreate {
  time_spent: string;
  worked_on?: string;
  category_id?: string | null;
  note?: string;
}

/** PATCH /worklogs/{id} — omitted keys untouched; null category_id clears it. */
export interface WorklogUpdate {
  time_spent?: string;
  worked_on?: string;
  category_id?: string | null;
  note?: string;
}

/** PUT /items/{id}/estimate. */
export interface EstimateSet {
  estimate: string; // duration text
}

/** GET /items/{id}/timelog — the per-item time-tracking summary. */
export interface ItemTimeSummary {
  item_id: string;
  enabled: boolean;
  original_estimate_seconds: number | null;
  original_estimate: string | null;
  logged_seconds: number;
  logged: string;
  remaining_seconds: number | null;
  remaining: string | null;
  entries: Worklog[];
}

/** One flat worklog row in a timesheet window (GET /timesheet). */
export interface TimesheetEntry {
  id: string;
  worked_on: string;
  time_spent_seconds: number;
  user: UserRef;
  /** Spec 59: null = an itemless (general) entry — category is its identity,
   *  project_key its optional project anchor. */
  item: ItemRef | null;
  /** Nearest epic ancestor of `item` — null for general worklogs and for
   *  issues that sit outside any epic. */
  epic: ItemRef | null;
  project_key: string | null;
  category: CategoryRef | null;
  note: string;
  /** RADD-1258 — "" or the VcsProvider the entry was mirrored from. */
  external_source: string;
}

/** GET /timesheet — entries the UI pivots into day/week/month grids. */
export interface Timesheet {
  start: string;
  end: string;
  total_seconds: number;
  entries: TimesheetEntry[];
  /** Outlier-flag config, resolved server-side from settings. */
  day_min_hours: number;
  day_max_hours: number;
  /** Working days ("mon".."sun") — under-logging only flags these. */
  work_days: string[];
  /** RADD-1574: who the sheet covers when a team was asked for — its members,
   *  with or without entries — and the Team view's thresholds. */
  people: UserRef[];
  hours_per_day: number;
  attention_low_percent: number;
  attention_high_percent: number;
  attention_days_percent: number;
  work_day_start_hour: number;
}

/** Why an issue is on a person's "my tickets" list (RADD-1572) — the server's `TicketReason`. */
export const TicketReason = { assigned: "assigned", logged: "logged", acted: "acted" } as const;
export type TicketReasonValue = (typeof TicketReason)[keyof typeof TicketReason];

/** One issue the caller is likely to log time on (`GET /timesheet/my-tickets`). */
export interface MyTicket {
  id: string;
  key: string;
  title: string;
  project_id: string;
  /** Newest reason first. */
  reasons: TicketReasonValue[];
  /** What they last did on it ("Comment added") when that is the newest reason. */
  activity: string;
  last_at: string;
  /** Everything the caller has logged on it. */
  my_seconds: number;
  /** False = its project has time logging switched off. */
  loggable: boolean;
}
