/** The ai plugin's reading-side wire shapes (specs 46/101/103): its status gate, editor actions,
 *  summaries, similar issues, the palette's Ask (semantic search) and the query bar's natural
 *  language (RADD-1400). Settings → AI's registry shapes live in `settings/types.ts`. */

/** Per-feature keys of `AiStatus.features` (spec 101). */
export const AiFeature = {
  editorActions: "editor_actions",
  semanticSearch: "semantic_search",
  summarize: "summarize",
  nlSlq: "nl_slq",
  similarRerank: "similar_rerank",
} as const;
export type AiFeatureValue = (typeof AiFeature)[keyof typeof AiFeature];

/** GET /ai/status — every AI affordance gates on `enabled`, and per feature on `features`
 * (toggle AND role resolvable). */
export interface AiStatus {
  enabled: boolean;
  features: Partial<Record<AiFeatureValue, boolean>>;
  /** Instance delivery preference: stream summaries/reasons progressively. */
  stream_responses: boolean;
}

/** Where an editor action comes from (spec 103): shipped builtin vs admin preset. */
export const AiEditorActionKind = { builtin: "builtin", preset: "preset" } as const;
export type AiEditorActionKindValue = (typeof AiEditorActionKind)[keyof typeof AiEditorActionKind];

/** One entry of GET /ai/editor/actions — the editor's curated AI menu. Builtin ids are stable
 * names; preset ids are the admin presets' uuids. */
export interface AiEditorAction {
  id: string;
  label: string;
  kind: AiEditorActionKindValue;
}

/** Stable builtin editor-action ids (the server's EditorAction enum) the UI addresses directly —
 * the read-mode menu runs Summarize as a query. */
export const AiBuiltinEditorAction = { summarize: "summarize_selection" } as const;

/** POST /items/{id}/ai/summarize — markdown, transient (never stored). */
export interface AiSummary {
  summary: string;
}

/** One candidate duplicate (GET /items/{id}/similar, POST /ai/similar). */
export interface SimilarCandidate {
  item_key: string;
  title: string;
  /** 0..1 — normalized rank, or the model's same-issue score. */
  score: number;
  reason: string;
}

export interface SimilarResponse {
  candidates: SimilarCandidate[];
  /** False = raw fused order (the rerank is off, or its reply didn't parse). */
  reranked: boolean;
}

/** One frame of POST /items/{id}/ai/similar/reasons (SSE): the model's score + reasoning for a
 * displayed candidate, hydrated row by row. */
export interface SimilarReason {
  key: string;
  score: number;
  reason: string | null;
}

/** Where "Find similar issues" seeds from: the item itself (its stored embedding + rerank) or a
 * text seed (a comment, a page — the text IS the subject and has no vector of its own). */
export type SimilarSeed = { itemId: string } | { seedKey: string; excludeItemId?: string };

/** One answer the reading pane (or the read menu's popover) shows. */
export type AiResultRequest =
  | { kind: "similar"; seed: SimilarSeed; text: string }
  | { kind: "item-summary"; itemId: string }
  | { kind: "text-summary"; text: string; imagesOf?: ImagesOf };

/** The entity whose image attachments a summary may show the vision role (RADD-1275). */
export interface ImagesOf {
  entity_type: string;
  entity_id: string;
}

/** GET /search/semantic (spec 103) — the palette's Ask: one probe by meaning over items + pages. */
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
  /** False = semantic search isn't configured here (no live provider) — never an error. */
  enabled: boolean;
  items: SemanticItem[];
  docs: SemanticDoc[];
}

/** POST /slq/nl (spec 46) — natural language → a validated SLQ query in a dialect (spec 98). */
export interface NlQueryRequest {
  question: string;
  dialect?: string;
}

export interface NlQueryResponse {
  slq: string;
  explanation: string;
}
