export interface HistoryChange {
  field: string;
  from?: unknown;
  to?: unknown;
  added?: unknown[];
  removed?: unknown[];
  key?: string;
  name?: string;
  /** Values withheld: the actor may not read this field (RADD-834). */
  redacted?: boolean;
}
