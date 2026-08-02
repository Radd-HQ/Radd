/** Leave + team holidays (timesheet wave). */

export const LeaveKind = { leave: "leave", holiday: "holiday" } as const;
export type LeaveKindValue = (typeof LeaveKind)[keyof typeof LeaveKind];

export interface LeavePeriod {
  id: string;
  user_id: string | null;
  team_id: string | null;
  team_name: string | null;
  kind: LeaveKindValue;
  label: string;
  start_date: string;
  end_date: string;
  created_by: string | null;
}

/** One user's absence span — holidays arrive pre-expanded per member. */
export interface LeaveCalendarEntry {
  user_id: string;
  kind: LeaveKindValue;
  label: string;
  start_date: string;
  end_date: string;
}

/** Someone away TODAY — what the app-wide avatar indicator renders from. */
export interface CurrentLeave {
  user_id: string;
  kind: LeaveKindValue;
  label: string;
  until: string;
}

export interface LeaveCreate {
  user_id?: string;
  team_id?: string;
  label?: string;
  start_date: string;
  end_date: string;
}
