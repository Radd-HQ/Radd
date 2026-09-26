import { ApiError, errorMessage } from "@radd/plugin-sdk";

/** The ai plugin's endpoints and how its failures read; `sse.ts` reads its streams. */

export const AiEndpoint = {
  status: "/ai/status",
  /** Similar issues for a TEXT seed (read-mode actions on comments and pages, the submission form). */
  similar: "/ai/similar",
  editorActions: "/ai/editor/actions",
  editorStream: "/ai/editor/stream",
  mePreferences: "/auth/me/preferences",
  /** The palette's Ask (RADD-1400): search's route, answered from this plugin's vectors. */
  searchSemantic: "/search/semantic",
  /** The query bar's natural language → SLQ (RADD-1400). */
  nlQuery: "/slq/nl",
} as const;

export const itemSummarizePath = (itemId: string) => `/items/${itemId}/ai/summarize`;
export const itemSummarizeStreamPath = (itemId: string) => `/items/${itemId}/ai/summarize/stream`;
export const itemSimilarPath = (itemId: string) => `/items/${itemId}/similar`;
/** SSE: per-candidate reasoning for a displayed similar list. */
export const itemSimilarReasonsPath = (itemId: string) => `/items/${itemId}/ai/similar/reasons`;

/** The module's error contract (spec 46): 502 = provider/network failure (clean message), 404 = AI
 * is disabled (plugin withdrawn) — affordances hide rather than show a dead error. */
export const AI_PROVIDER_UNAVAILABLE_MESSAGE = "AI provider unavailable.";

/** True when an AI call 404'd — the plugin was disabled (possibly mid-session). */
export function isAiGone(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/** Inline error text for an AI call: 502 → the provider message, else as-is. */
export function aiErrorText(error: unknown): string {
  if (error instanceof ApiError && error.status === 502) return AI_PROVIDER_UNAVAILABLE_MESSAGE;
  return errorMessage(error);
}
