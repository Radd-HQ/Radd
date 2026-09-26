/** Search (spec 28). */
// ---------------------------------------------------------------------------
// Search (search module — spec 28)
// ---------------------------------------------------------------------------

export interface SearchResult {
  item_id: string;
  project_id: string;
  key: string;
  title: string;
  /** ts_headline fragment with <b>…</b> marks; null for key-prefix hits. */
  snippet: string | null;
}

export interface SearchResponse {
  results: SearchResult[];
}

// ---------------------------------------------------------------------------
// Semantic search (spec 103) — GET /search/semantic, the palette's Ask mode
// ---------------------------------------------------------------------------

export interface SemanticItem {
  item_id: string;
  project_id: string;
  key: string;
  title: string;
  /** 1 − cosine distance, 0..1. */
  score: number;
}

export interface SemanticDoc {
  page_id: string;
  space_id: string;
  title: string;
  score: number;
}

export interface SemanticResponse {
  /** False = semantic search isn't configured here — hide the Ask affordance. */
  enabled: boolean;
  items: SemanticItem[];
  docs: SemanticDoc[];
}

/** RADD-1327: one hit from any registered searchable type (a plugin's too). */
export interface EntityHit {
  entity_type: string;
  id: string;
  title: string;
  subtitle: string | null;
  /** Site-relative — where the owner says this entity lives. */
  url: string;
  snippet: string | null;
}

export interface EntitySearchGroup {
  entity_type: string;
  label: string;
  hits: EntityHit[];
}

export interface EntitySearchResponse {
  groups: EntitySearchGroup[];
}

/** GET /search/deflect (spec 66) — KB deflection under the new-issue title:
 * pages pages that may already answer it + previously RESOLVED items. */
export interface DeflectPage {
  id: string;
  space_id: string;
  title: string;
  space_name: string;
}

export interface DeflectItem {
  key: string;
  title: string;
}

export interface DeflectResponse {
  docs: DeflectPage[];
  items: DeflectItem[];
}
