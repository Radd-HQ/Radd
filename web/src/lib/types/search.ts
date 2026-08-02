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
