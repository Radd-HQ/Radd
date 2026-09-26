import { queryOptions, useQuery } from "@tanstack/react-query";
import { api, useIsAuthenticated } from "@radd/plugin-sdk";
import { AiEntity } from "./settings/types";
import { AiEndpoint, itemSimilarPath } from "./transport";
import type { AiEditorAction, AiStatus, SimilarResponse } from "./types";

/**
 * The ai plugin's reads (RADD-1395). Every key starts with "ai", so withdrawing the plugin drops
 * them with it (the loader removes a plugin's own query keys) and a re-enable reads afresh.
 */

/**
 * GET /ai/status — gates every AI affordance. A 404 (plugin disabled) rejects; consumers treat
 * error/undefined as disabled and render nothing. Tagged with the provider/role entities, so a
 * change on Settings → AI refreshes the gate.
 */
export const aiStatusQuery = queryOptions({
  queryKey: ["ai", "status"],
  meta: { entities: [AiEntity.provider, AiEntity.role] },
  queryFn: ({ signal }) => api.get<AiStatus>(AiEndpoint.status, { signal }),
  staleTime: 60_000,
  retry: false,
});

/** The status gate, asked only by an account (a visitor's request would 401). */
export function useAiStatus() {
  return useQuery({ ...aiStatusQuery, enabled: useIsAuthenticated() });
}

/** GET /ai/editor/actions — the editor's curated menu (builtins + enabled presets). */
export const aiEditorActionsQuery = queryOptions({
  queryKey: ["ai", "editor-actions"],
  // The enabled presets are part of the menu; editing one on Settings → AI refreshes it.
  meta: { entities: [AiEntity.preset] },
  queryFn: ({ signal }) => api.get<AiEditorAction[]>(AiEndpoint.editorActions, { signal }),
  staleTime: 60_000,
  retry: false,
});

/** The account's preferences dict (spec 94) — the editor-AI opt-out lives in it. */
export const aiPreferencesQuery = queryOptions({
  queryKey: ["ai", "preferences"],
  queryFn: ({ signal }) => api.get<Record<string, unknown>>(AiEndpoint.mePreferences, { signal }),
  staleTime: 60_000,
});

/** Candidate duplicates for an item — fetched on demand (pair with `enabled`), transient. */
export const similarItemsQuery = (itemId: string) =>
  queryOptions({
    queryKey: ["ai", "similar-items", itemId],
    queryFn: ({ signal }) => api.get<SimilarResponse>(itemSimilarPath(itemId), { signal }),
    retry: false,
    staleTime: 30_000,
  });

/**
 * Similar issues for a TEXT seed — fused pools, never reranked. `seedKey` names the text's origin
 * (a comment or page id). The text and excluded issue belong in the cache identity too, so editing
 * the comment or changing its context cannot reuse an older result.
 */
export const similarToTextQuery = (seedKey: string, text: string, excludeItemId?: string) =>
  queryOptions({
    queryKey: ["ai", "similar-text", seedKey, text, excludeItemId ?? null],
    queryFn: ({ signal }) =>
      api.post<SimilarResponse>(AiEndpoint.similar, { text, exclude_item_id: excludeItemId ?? null }, { signal }),
    retry: false,
    staleTime: 30_000,
  });
