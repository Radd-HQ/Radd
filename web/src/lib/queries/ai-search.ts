/** The AI status gate (spec 46), KB deflection (spec 66), and palette search (spec 28). Every
 * other AI read — editor actions, similar issues, summaries — is the ai plugin's (RADD-1395). */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import { ApiPath, DEFLECT_MIN_QUERY_CHARS } from "../constants";
import { queryKeys } from "./shared";
import type {
  AiStatus,
  DeflectResponse,
  SearchResponse,
  EntitySearchResponse,
  SemanticResponse,
} from "../types";

/**
 * GET /ai/status (spec 46) — gates the query bar's Ask mode and the palette's semantic search, the
 * two AI affordances still in the host (RADD-1395). A 404 (plugin disabled) rejects; consumers
 * treat error/undefined as disabled and render nothing. Tagged with the provider/role entities
 * because the ai plugin's settings page (RADD-1379) invalidates by tag: a provider or role change
 * there refreshes this gate without either side knowing the other's query keys.
 */
export const aiStatusQuery = queryOptions({
  queryKey: queryKeys.aiStatus,
  meta: entityMeta(Entity.aiProvider, Entity.aiRole),
  queryFn: ({ signal }) => api.get<AiStatus>(ApiPath.aiStatus, { signal }),
  staleTime: 60_000,
  retry: false,
});

/** KB deflection (spec 66): pages pages + previously RESOLVED items for a
 * half-typed issue title. The DeflectionPanel debounces `q` before this. */
export const deflectQuery = (q: string, projectId: string) =>
  queryOptions({
    queryKey: queryKeys.deflect(q, projectId),
    queryFn: ({ signal }) =>
      api.get<DeflectResponse>(ApiPath.searchDeflect, {
        signal,
        query: { q, project_id: projectId },
      }),
    placeholderData: keepPreviousData,
    enabled: q.trim().length >= DEFLECT_MIN_QUERY_CHARS && projectId !== "",
  });

/** Palette search-as-you-type (spec 28) — key prefix + full text, RBAC-scoped. */
/** RADD-1327: every registered searchable type, grouped; `exclude` leaves out
 *  the types a caller already queries on its own (the palette's issues/pages). */
export const entitySearchQuery = (q: string, opts: { exclude?: string; mentionable?: boolean; limit?: number }) => {
  const query: Record<string, string> = { q, limit: String(opts.limit ?? 5) };
  if (opts.exclude) query.exclude = opts.exclude;
  if (opts.mentionable) query.mentionable = "true";
  return queryOptions({
    queryKey: queryKeys.searchEntities(q, query),
    queryFn: ({ signal }) => api.get<EntitySearchResponse>(ApiPath.searchEntities, { signal, query }),
    placeholderData: keepPreviousData,
    enabled: q.trim().length > 0,
  });
};

export const searchQuery = (q: string, limit: number) =>
  queryOptions({
    queryKey: queryKeys.search(q, limit),
    queryFn: ({ signal }) =>
      api.get<SearchResponse>(ApiPath.search, {
        signal,
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
    queryFn: ({ signal }) => api.get<SemanticResponse>(ApiPath.searchSemantic, { signal, query: { q } }),
    placeholderData: keepPreviousData,
    retry: false,
    enabled: q.trim().length > 0,
  });
