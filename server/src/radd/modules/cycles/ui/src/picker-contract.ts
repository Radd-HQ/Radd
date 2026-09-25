import type { Cycle } from "./types";
export const CYCLE_SELECT_SLOT = "cycles.select";
export const CYCLE_CHOICES_SLOT = "cycles.choices";
export interface CycleSelectProps {
  value: string;
  onChange: (value: string, cycle: Cycle | null) => void;
  /** Automation and form defaults persist names; issue fields persist IDs. */
  valueBy?: "id" | "name";
  selectedLabel?: string;
  label?: string;
  placeholder?: string;
  emptyLabel?: string | null;
  emptyValue?: string;
  includeCompleted?: boolean;
  datedOnly?: boolean;
  disabled?: boolean;
  title?: string;
  error?: string;
  hint?: string;
  id?: string;
  size?: "sm" | "md";
  className?: string;
  /** RADD-1291: open on this project's cycles, with a switch to see all of them
   *  (a cycle may still hold issues from any project). */
  projectId?: string;
}

export interface CycleChoicesProps {
  value?: string; valueBy?: "id" | "name"; emptyLabel?: string | null;
  includeCompleted?: boolean; datedOnly?: boolean; projectId?: string;
  onSelect: (cycle: Cycle | null) => void; onClose: () => void;
}
