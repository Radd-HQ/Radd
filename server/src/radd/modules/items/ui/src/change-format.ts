import type { HistoryChange } from "@radd/plugin-sdk";
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
export function itemChange(change: HistoryChange): HistoryChange {
  const label = change.name ?? HISTORY_FIELD_LABELS[change.field];
  if (change.redacted) return { field: change.field, name: label, redacted: true };
  const value = (v: unknown) => change.field === "priority" && typeof v === "string" ? PRIORITY_LABELS[v] ?? v : v;
  const links = (entries: unknown[] | undefined) => entries?.map(entry => {
    if (entry && typeof entry === "object" && "key" in entry && "link_type" in entry) return `${entry.key} (${entry.link_type})`;
    return entry;
  });
  return { ...change, name: label,
    ...("from" in change ? {from: value(change.from)} : {}), ...("to" in change ? {to: value(change.to)} : {}),
    ...(change.field === "links" && "added" in change ? {added: links(change.added)} : {}),
    ...(change.field === "links" && "removed" in change ? {removed: links(change.removed)} : {}),
  };
}
