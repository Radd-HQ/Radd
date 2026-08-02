/** AI status/similars (spec 46), KB deflection (spec 66), and palette search (spec 28). */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  DEFLECT_MIN_QUERY_CHARS,
  apiItemSimilarPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  AiEditorAction,
  AiStatus,
  DeflectResponse,
  SearchResponse,
  SemanticResponse,
  SimilarResponse,
} from "../types";

/**
 * GET /ai/status (spec 46) — gates every AI affordance. A 404 (module not
 * mounted) rejects; consumers treat error/undefined as disabled and render
 * nothing. Transient config, no entity tags.
 */
export const aiStatusQuery = queryOptions({
  queryKey: queryKeys.aiStatus,
  queryFn: () => api.get<AiStatus>(ApiPath.aiStatus),
  staleTime: 60_000,
  retry: false,
});

/**
 * GET /ai/editor/actions (spec 103) — the editor's curated AI menu (builtins +
 * enabled presets). Pair with `enabled` gated on aiStatus's editor_actions
 * feature; a 404 means the feature went dormant mid-session (render nothing).
 */
export const aiEditorActionsQuery = queryOptions({
  queryKey: queryKeys.aiEditorActions,
  queryFn: () => api.get<AiEditorAction[]>(ApiPath.aiEditorActions),
  staleTime: 60_000,
  retry: false,
});

/**
 * Candidate duplicates for an item (spec 46) — fetched on demand (pair with
 * `enabled`), transient (no entity tags), a 404 means AI got disabled.
 */
export const similarItemsQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.similarItems(itemId),
    queryFn: () => api.get<SimilarResponse>(apiItemSimilarPath(itemId)),
    retry: false,
    staleTime: 30_000,
  });

/**
 * Similar issues for a TEXT seed (read-mode AI menu on a comment) — fused
 * FTS + vector pools, never reranked. `seedKey` names the text's origin (the
 * comment id) so the cache key stays small and stable while the comment text
 * itself rides in the POST body.
 */
export const similarToTextQuery = (seedKey: string, text: string, excludeItemId?: string) =>
  queryOptions({
    queryKey: queryKeys.similarToText(seedKey),
    queryFn: () =>
      api.post<SimilarResponse>(ApiPath.aiSimilar, {
        text,
        exclude_item_id: excludeItemId ?? null,
      }),
    retry: false,
    staleTime: 30_000,
  });

/** KB deflection (spec 66): pages pages + previously RESOLVED items for a
 * half-typed issue title. The DeflectionPanel debounces `q` before this. */
export const deflectQuery = (q: string, projectId: string) =>
  queryOptions({
    queryKey: queryKeys.deflect(q, projectId),
    queryFn: () =>
      api.get<DeflectResponse>(ApiPath.searchDeflect, {
        query: { q, project_id: projectId },
      }),
    placeholderData: keepPreviousData,
    enabled: q.trim().length >= DEFLECT_MIN_QUERY_CHARS && projectId !== "",
  });

/** Palette search-as-you-type (spec 28) — key prefix + full text, RBAC-scoped. */
export const searchQuery = (q: string, limit: number) =>
  queryOptions({
    queryKey: queryKeys.search(q),
    queryFn: () =>
      api.get<SearchResponse>(ApiPath.search, {
        query: { q, limit: String(limit) },
      }),
    meta: entityMeta(Entity.item),
    placeholderData: keepPreviousData,
    enabled: q.trim().length > 0,
  });

/** Palette Ask mode (spec 103): ONE semantic probe over items + docs.
 * `enabled: false` in the payload = not configured — the UI hides the mode.
 * Transient (no entity tags); a 404 means the search module lacks the route. */
export const semanticSearchQuery = (q: string) =>
  queryOptions({
    queryKey: queryKeys.searchSemantic(q),
    queryFn: () => api.get<SemanticResponse>(ApiPath.searchSemantic, { query: { q } }),
    placeholderData: keepPreviousData,
    retry: false,
    enabled: q.trim().length > 0,
  });
