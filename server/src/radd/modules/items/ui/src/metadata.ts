export const HISTORY_FIELD_LABELS: Record<string, string> = {
  title: "Title",
  description: "Description",
  state: "State",
  priority: "Priority",
  assignee: "Assignee",
  reporter: "Reporter",
  team: "Team",
  parent: "Parent",
  cycle: "Cycle",
  release: "Release",
  start_date: "Start date",
  target_date: "Target date",
  flagged: "Flag",
  labels: "Labels",
  links: "Dependencies",
  custom_field: "Field",
};
export const PRIORITY_LABELS: Record<string, string> = { blocker: "Blocker", high: "High", normal: "Normal", low: "Low" };
export const PRIORITY_ORDER = ["blocker", "high", "normal", "low"] as const;
export const VISIBILITY_LABELS = {public: "Public", internal: "Members only", restricted: "Restricted"} as const;
export const VISIBILITY_ORDER = ["public", "internal", "restricted"] as const;
