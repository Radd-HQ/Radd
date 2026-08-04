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

export interface AuditEntry {
  id: number;
  at: string;
  actor: AuditActor | null;
  event_type: string;
  entity_type: string;
  entity_id: string;
  changes?: HistoryChange[] | null;
}
