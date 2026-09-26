import type { HistoryChange } from "@radd/plugin-sdk";
/** The grant record is emitted by Auth alongside role history. */
export function roleChange(change: HistoryChange): HistoryChange {
  if (change.redacted) return {field: change.field, name: change.name, redacted: true};
  if (change.field !== "grants") return change;
  const grants = (values: unknown[] | undefined) => values?.map(value => {
    if (!value || typeof value !== "object" || !("subject" in value) || typeof value.subject !== "string") return value;
    const role = "role" in value && typeof value.role === "string" ? ` as ${value.role}` : "";
    const scope = "scope" in value && typeof value.scope === "string" ? ` (${value.scope})` : "";
    return `${value.subject}${role}${scope}`;
  });
  return {...change, ...("added" in change ? {added: grants(change.added)} : {}),
    ...("removed" in change ? {removed: grants(change.removed)} : {})};
}
