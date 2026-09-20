/** AI layer (spec 46): status gate, summaries, similar items, NL → SLQ.
 * Spec 101 adds the provider registry (Settings → AI): providers, roles, presets. */
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

/** Wire protocol a provider speaks (spec 101). */
export const AiWireShape = {
  openai: "openai",
  anthropic: "anthropic",
  // The ai plugin's built-in CPU embedding backend — embeddings role only.
  local: "local",
} as const;
export type AiWireShapeValue = (typeof AiWireShape)[keyof typeof AiWireShape];

/** Where a provider row came from — env-seeded rows are ordinary editable rows. */
export const AiProviderSource = {
  env: "env",
  user: "user",
} as const;
export type AiProviderSourceValue = (typeof AiProviderSource)[keyof typeof AiProviderSource];

/** What a configured model is FOR — features resolve a role, never a provider. */
export const AiRole = {
  chat: "chat",
  embeddings: "embeddings",
  vision: "vision",
} as const;
export type AiRoleValue = (typeof AiRole)[keyof typeof AiRole];

/** Per-feature keys of `AiStatus.features` (spec 101). */
export const AiFeature = {
  editorActions: "editor_actions",
  semanticSearch: "semantic_search",
  storageRouting: "storage_routing",
  mailRouting: "mail_routing",
  summarize: "summarize",
  nlSlq: "nl_slq",
  similarRerank: "similar_rerank",
} as const;
export type AiFeatureValue = (typeof AiFeature)[keyof typeof AiFeature];

/** One provider row from GET /ai/providers — the api key never leaves the server. */
export interface AiProviderRead {
  id: string;
  name: string;
  wire_shape: AiWireShapeValue;
  /** "" = the wire shape's default endpoint. */
  base_url: string;
  has_api_key: boolean;
  default_model: string;
  source: AiProviderSourceValue;
  /** RADD-1273: off = Radd asks a thinking model not to think (the default);
   *  on = the model's own default. */
  reasoning: boolean;
  /** Admin-supplied JSON object merged LAST into every chat payload. */
  request_params: Record<string, unknown>;
}

/** POST /ai/providers body; PATCH sends a partial ("" api_key = keep stored). */
export interface AiProviderPayload {
  name: string;
  wire_shape: AiWireShapeValue;
  base_url?: string;
  api_key?: string;
  default_model?: string;
  reasoning?: boolean;
  request_params?: Record<string, unknown>;
}

/** One role assignment from GET /ai/roles (unassigned roles have no row). */
export interface AiRoleRead {
  role: AiRoleValue;
  provider_id: string;
  provider_name: string;
  /** "" = fall back to the provider's default model. */
  model: string;
  effective_model: string;
}

/** POST /ai/providers/{id}/test — failures come back as data, never a 502. */
export interface AiProbeResult {
  ok: boolean;
  error: string;
  latency_ms: number | null;
}

/** Where an editor action comes from (spec 103): shipped builtin vs admin preset. */
export const AiEditorActionKind = {
  builtin: "builtin",
  preset: "preset",
} as const;
export type AiEditorActionKindValue = (typeof AiEditorActionKind)[keyof typeof AiEditorActionKind];

/** One entry of GET /ai/editor/actions — the editor's curated AI menu (spec 103).
 * Builtin ids are stable names; preset ids are the AiPreset uuids. */
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

/** One editor-action preset prompt (spec 101; consumed by the spec-103 editor menu). */
export interface AiPreset {
  id: string;
  name: string;
  prompt: string;
  enabled: boolean;
  position: number;
}

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

export interface EmbeddingCoverage {
  enabled: boolean;
  items_total: number;
  items_embedded: number;
  docs_total: number;
  docs_embedded: number;
}
