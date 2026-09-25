import { CycleStatus, type CycleStatusValue } from "./types";
interface StatusMeta { label: string; dotClassName: string; pillClassName?: string }

export const CYCLE_STATUS_META: Record<CycleStatusValue, StatusMeta> = {
  [CycleStatus.draft]: {
    label: "Draft",
    dotClassName: "bg-fg-secondary",
    pillClassName: "border-emphasis/60 bg-elevated/60 text-fg",
  },
  // Upcoming/active ride the workflow-state scale (RADD-900): a queued cycle
  // is the todo blue, a running one the progress green — the same traffic-light
  // reading as items, and the raw blue-200/emerald-200 shades they used had no
  // light remap (stock blue-200 on white is ~1.4:1).
  [CycleStatus.upcoming]: {
    label: "Upcoming",
    dotClassName: "bg-chart-todo",
    pillClassName: "border-chart-todo/40 bg-chart-todo/12 text-chart-todo-ink",
  },
  [CycleStatus.active]: {
    label: "Active",
    dotClassName: "bg-chart-progress",
    pillClassName: "border-chart-progress/40 bg-chart-progress/12 text-chart-progress-ink",
  },
  [CycleStatus.completed]: {
    label: "Completed",
    dotClassName: "bg-fg-faint",
    pillClassName: "border-strong bg-elevated/40 text-fg-muted",
  },
};

