/** The audit log's URL filter shape and the entity links in its rows (spec 123). No value
 *  imports: `audit-links.test.mjs` loads this file on its own. */
import type { AuditEntry, AuditSourceValue } from "./types";
import { defaultParseSearch } from "@tanstack/react-router";

/** Every filter rides in the URL — short inline params, shareable as they are. */
export interface AuditSearch {
  project?: string;
  entity?: string;
  entity_id?: string;
  actor?: string;
  field?: string;
  source?: AuditSourceValue;
  from?: string;
  to?: string;
  q?: string;
  noise?: boolean;
}

const SOURCES = new Set(["people", "automations", "system"]);

function str(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

export function parseAuditSearch(search: Record<string, unknown>): AuditSearch {
  const source = str(search.source);
  return {
    project: str(search.project),
    entity: str(search.entity),
    entity_id: str(search.entity_id),
    actor: str(search.actor),
    field: str(search.field),
    source: source && SOURCES.has(source) ? (source as AuditSourceValue) : undefined,
    from: str(search.from),
    to: str(search.to),
    q: str(search.q),
    noise: search.noise === true || search.noise === "true" ? true : undefined,
  };
}

/** A router `to` + params for the entity a row is about, or null when nothing links. */
interface AuditLink {
  to: string;
  params?: Record<string, string>;
  search?: Record<string, string | number>;
}

/** An authorized audit row carries its owner's current destination. A cached
 * row cannot keep a link alive after its owner disappears from capabilities. */
export function auditEntityLink(entry: AuditEntry, availablePlugins: ReadonlySet<string>): AuditLink | null {
  if (!entry.entity_owner || !availablePlugins.has(entry.entity_owner)) return null;
  const value = entry.entity_url;
  if (!value || !value.startsWith("/") || value.startsWith("//") || /[\\\x00-\x1f\x7f]/.test(value)) return null;
  const url = new URL(value, "https://radd.invalid");
  if (url.origin !== "https://radd.invalid") return null;
  return { to: url.pathname + url.hash, search: defaultParseSearch(url.search) };
}

/** "Hussein · Role updated · Contributor" — the row's sentence, in three parts. */
export function auditSentence(entry: AuditEntry): { who: string; did: string; what: string } {
  return {
    who: entry.actor?.name ?? (entry.automated ? "An automation" : "System"),
    did: entry.event_label,
    what: entry.entity_label ?? entry.entity_id,
  };
}
