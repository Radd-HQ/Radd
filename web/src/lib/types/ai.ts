/** The AI status gate (spec 46) and natural language → SLQ — what the host's query bar (Ask mode)
 * and command palette (semantic search) still read. Every other AI shape — editor actions,
 * summaries, similar issues — is the ai plugin's (RADD-1395); the provider registry's is its
 * Settings → AI page's (RADD-1379). */
/** GET /ai/status (spec 46); since spec 101 also per-feature on `features` (toggle AND role
 * resolvable). */
export interface AiStatus {
  enabled: boolean;
  features: Partial<Record<AiFeatureValue, boolean>>;
  /** Instance delivery preference: stream summaries/reasons progressively. */
  stream_responses: boolean;
}

/** Per-feature keys of `AiStatus.features` the host reads (spec 101). */
export const AiFeature = {
  semanticSearch: "semantic_search",
} as const;
export type AiFeatureValue = (typeof AiFeature)[keyof typeof AiFeature];

/** POST /slq/nl (spec 46) — natural language → a validated SLQ query. */
export interface NlQueryRequest {
  question: string;
  /** SLQ surface (spec 98): "worklog" on the timesheet, "items" everywhere else. */
  dialect?: "items" | "worklog";
}

export interface NlQueryResponse {
  slq: string;
  explanation: string;
}
