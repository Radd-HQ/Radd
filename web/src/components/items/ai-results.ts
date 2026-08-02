import { createContext, useContext } from "react";

/** Where "Find similar issues" seeds from: the item itself (uses its stored
 * embedding + LLM rerank) or a text seed (comments, wiki pages — the text IS
 * the subject and has no vector of its own). */
export type SimilarSeed = { itemId: string } | { seedKey: string; excludeItemId?: string };

/** One AI result the issue page can display in its results pane. */
export type AiResultRequest =
  | { kind: "similar"; seed: SimilarSeed; text: string }
  | { kind: "item-summary"; itemId: string }
  | { kind: "text-summary"; text: string };

/**
 * Provided by the issue detail body: opens the AI results pane beside the
 * reading column (the dead space) instead of answering in a cramped popover
 * or the w-72 rail. Null outside the issue page (wiki pages, plain editors) —
 * callers fall back to their local presentation.
 */
export const AiResultsContext = createContext<((request: AiResultRequest) => void) | null>(null);

export function useOpenAiResults(): ((request: AiResultRequest) => void) | null {
  return useContext(AiResultsContext);
}
