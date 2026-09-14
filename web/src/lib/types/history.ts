/** Item history / activity feed + the admin audit log projection. */
import type { ItemKindValue } from "./items";
// ---------------------------------------------------------------------------
// Item history / activity feed (audit) — GET /items/{id}/history
// ---------------------------------------------------------------------------

export interface HistoryActor {
  id: string;
  name: string;
}

/** A far-item reference inside a `links` change (added/removed dependency). */
export interface LinkChangeRef {
  link_type: string;
  key: string;
  title: string;
}

/**
 * One field change in an `item.updated` event. Which keys are present depends on
 * `field`: scalars/relations use from/to; `labels`/`links` use added/removed;
 * `custom_field` adds key/name; `description` carries only `field`.
 */
export interface HistoryChange {
  field: string;
  from?: string | number | boolean | null;
  to?: string | number | boolean | null;
  added?: (string | LinkChangeRef)[];
  removed?: (string | LinkChangeRef)[];
  key?: string;
  name?: string;
  /** Values withheld: the actor may not read this field (RADD-834). */
  redacted?: boolean;
}

export interface HistoryEntry {
  id: number;
  at: string;
  actor: HistoryActor | null;
  type: string; // event_type, e.g. "item.created", "item.updated", "comment.created"
  changes: HistoryChange[];
  detail: Record<string, unknown> | null;
}

export interface ItemHistory {
  entries: HistoryEntry[];
}

/** GET /items/link-search — a candidate item for the dependency typeahead. */
export interface ItemLinkSearchResult {
  id: string;
  number: number;
  key: string;
  title: string;
  kind: ItemKindValue;
}
// ---------------------------------------------------------------------------
// Admin audit log (audit module — read-only projection of the event stream)
// ---------------------------------------------------------------------------

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
