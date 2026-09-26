/** AI layer (spec 46): status gate, summaries, similar items, NL → SLQ, editor actions.
 * The provider registry's types (Settings → AI) belong to the ai plugin's UI (RADD-1379). */
/** GET /ai/status (spec 46) — every AI affordance in the UI gates on `enabled`;
 * since spec 101 also per-feature on `features` (toggle AND role resolvable). */
export interface AiStatus {
  enabled: boolean;
  features: Partial<Record<AiFeatureValue, boolean>>;
  /** Instance delivery preference: stream summaries/reasons progressively. */
  stream_responses: boolean;
}

/** One frame of POST /items/{id}/ai/similar/reasons (SSE): the LLM's score +
 * reasoning for a displayed candidate, hydrated row by row. */
export interface SimilarReason {
  key: string;
  score: number;
  reason: string | null;
}

/** Per-feature keys of `AiStatus.features` (spec 101). */
export const AiFeature = {
  editorActions: "editor_actions",
  semanticSearch: "semantic_search",
  storageRouting: "storage_routing",
  mailSignature: "mail_signature",
  mailRouting: "mail_routing",
  summarize: "summarize",
  nlSlq: "nl_slq",
  similarRerank: "similar_rerank",
} as const;
export type AiFeatureValue = (typeof AiFeature)[keyof typeof AiFeature];

/** Where an editor action comes from (spec 103): shipped builtin vs admin preset. */
export const AiEditorActionKind = {
  builtin: "builtin",
  preset: "preset",
} as const;
export type AiEditorActionKindValue = (typeof AiEditorActionKind)[keyof typeof AiEditorActionKind];

/** One entry of GET /ai/editor/actions — the editor's curated AI menu (spec 103).
 * Builtin ids are stable names; preset ids are the admin presets' uuids. */
export interface AiEditorAction {
  id: string;
  label: string;
  kind: AiEditorActionKindValue;
}

/** Stable builtin editor-action ids (the server's EditorAction enum) that the
 * UI addresses directly — the read-mode menu runs Summarize as a query. */
export const AiBuiltinEditorAction = {
  summarize: "summarize_selection",
} as const;

/** POST /items/{id}/ai/summarize — markdown, transient (never stored). */
export interface AiSummary {
  summary: string;
}

/** One candidate duplicate from GET /items/{id}/similar (spec 46). */
export interface SimilarCandidate {
  item_key: string;
  title: string;
  /** 0..1 — normalized FTS rank, or the LLM's same-issue score. */
  score: number;
  reason: string;
}

export interface SimilarResponse {
  candidates: SimilarCandidate[];
  /** False = raw FTS order (AI disabled, or the rerank reply didn't parse). */
  reranked: boolean;
}

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
