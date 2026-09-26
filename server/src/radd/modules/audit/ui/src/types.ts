import type { HistoryChange } from "@radd/plugin-sdk";
export interface AuditActor {
  id: string;
  name: string;
  email?: string | null;
}

export interface AuditProject {
  id: string;
  key: string;
  name: string;
}

/** A subject ref the payload carries (`item`, `page`, `page_space`, `project`…). */
export type AuditRef = Record<string, unknown> & { id?: string; key?: string; slug?: string };

export interface AuditEntry {
  id: number;
  at: string;
  actor: AuditActor | null;
  event_type: string;
  /** From the registered EventTypeSpec (spec 123) — never a hardcoded map. */
  event_label: string;
  event_group: string;
  entity_type: string;
  entity_id: string;
  /** Current owner-declared destination; absent for unavailable or unlinked types. */
  entity_url?: string | null;
  entity_owner?: string | null;
  /** The entity's display label at write time (`RADD-123 Board scroll`). */
  entity_label: string | null;
  refs: Record<string, AuditRef>;
  project: AuditProject | null;
  automated: boolean;
  silent: boolean;
  changes?: HistoryChange[] | null;
}

/** Who caused a row — the `source` filter (spec 123). */
export const AuditSource = {
  people: "people",
  automations: "automations",
  system: "system",
} as const;
export type AuditSourceValue = (typeof AuditSource)[keyof typeof AuditSource];

export interface AuditEventType {
  event_type: string;
  label: string;
  group: string;
  entity_type: string;
  has_changes: boolean;
  audited: boolean;
}

export interface AuditEntityType {
  key: string;
  label: string;
}

/** GET /audit/catalog — the registry's vocabulary the filters are built from. */
export interface AuditCatalog {
  event_types: AuditEventType[];
  entity_types: AuditEntityType[];
}
