/** Item history / activity feed. Structured changes use the shared event contract. */
import type { ItemKindValue } from "./items";
// ---------------------------------------------------------------------------
// Item history / activity feed (audit) — GET /items/{id}/history
// ---------------------------------------------------------------------------

interface HistoryActor {
  id: string;
  name: string;
}

/**
 * One field change in an `item.updated` event. Which keys are present depends on
 * `field`: scalars/relations use from/to; `labels`/`links` use added/removed;
 * `custom_field` adds key/name; `description` carries only `field`.
 */
import type { HistoryChange } from "@radd/plugin-sdk";

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
