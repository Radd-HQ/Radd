import type { TimesheetEntry, WorkCategory } from "../../lib/types";

/** Something a person can log time against from the tray. */
export interface Ticket {
  id: string;
  key: string;
  title: string;
  /** False = its project has time logging switched off: shown, not draggable. */
  loggable?: boolean;
}

/** What is being dragged over the week (RADD-1541). Held in state, not in the
 *  DataTransfer: a drop needs the whole object, and browsers hide a drag's data
 *  from `dragover`, which is when the target has to decide whether to light up. */
export type Dragged =
  | { kind: "ticket"; ticket: Ticket }
  | { kind: "category"; category: WorkCategory }
  | { kind: "entry"; entry: TimesheetEntry };

export interface WeekActions {
  /** Log `seconds` on `day` against a ticket, or (no ticket) a general category. */
  log: (target: { ticket?: Ticket; category?: WorkCategory }, day: string, seconds: number, note?: string) => void;
  update: (entry: TimesheetEntry, patch: { day?: string; seconds?: number; note?: string }) => void;
  remove: (entry: TimesheetEntry) => void;
  peek: (key: string) => void;
}
