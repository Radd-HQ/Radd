import type { HistoryChange } from "@radd/plugin-sdk";
import { HISTORY_FIELD_LABELS, PRIORITY_LABELS } from "./metadata";
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
