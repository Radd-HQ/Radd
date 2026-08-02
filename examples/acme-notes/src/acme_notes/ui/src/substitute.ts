import type { Item } from "@radd/plugin-sdk";

/**
 * `{{token}}` substitution against an issue — demonstrating that a plugin attached to an issue has
 * access to that issue's fields (the `item` the host hands it via slot props). The `item` is the
 * host's HYDRATED, permission-scoped object: only fields the current user may read are present, so
 * `{{cf:secret}}` for a field the user can't see resolves to empty — the plugin can't leak what the
 * user can't see (docs/plugin-platform.md §7.5).
 */

/** The tokens the note editor advertises (custom fields via `{{cf:<key>}}`). */
export const NOTE_TOKENS = [
  "key",
  "title",
  "state",
  "priority",
  "assignee",
  "reporter",
  "parent",
] as const;

export function substituteNote(text: string, item: Item): string {
  const rec = item as Record<string, unknown>;
  const ref = (v: unknown): string => {
    const o = v as { name?: string; key?: string; title?: string } | null | undefined;
    return o ? String(o.key ?? o.name ?? o.title ?? "") : "";
  };
  const resolve = (raw: string): string => {
    const t = raw.trim();
    if (t.startsWith("cf:")) {
      const cf = (rec.custom_fields ?? {}) as Record<string, unknown>;
      const v = cf[t.slice(3)];
      return v == null ? "" : String(v);
    }
    switch (t) {
      case "key": return String(item.key ?? "");
      case "number": return String(rec.number ?? "");
      case "title": return String(item.title ?? "");
      case "state": return item.state?.name ?? "";
      case "priority": return String(rec.priority ?? "");
      case "assignee": return ref(item.assignee);
      case "reporter": return ref(item.reporter);
      case "parent": return ref(rec.parent);
      default: return "";
    }
  };
  return text.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_m, tok: string) => resolve(tok));
}
