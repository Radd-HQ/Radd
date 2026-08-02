/** CSAT surveys (spec 65). */
// ---------------------------------------------------------------------------
// CSAT surveys (csat module — spec 65)
// ---------------------------------------------------------------------------

/** GET/POST /public/csat/{token} — the public rating page's payload. */
export interface PublicCsat {
  item_key: string;
  item_title: string;
  rating: number | null;
  responded_at: string | null;
}

export interface PublicCsatSubmit {
  rating: number; // 1..5
  comment?: string;
}

/** GET /items/{id}/csat — the ANSWERED survey (404 until responded). */
export interface ItemCsat {
  rating: number;
  comment: string;
  responded_at: string;
}
