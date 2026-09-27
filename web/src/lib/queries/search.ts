/** Keyword search (spec 28), every registered searchable (RADD-1327) and KB deflection (spec 66).
 * The palette's other faces are contributed modes (RADD-1400). */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "@radd/plugin-sdk";
import { ApiPath, DEFLECT_MIN_QUERY_CHARS } from "../constants";
import { queryKeys } from "./shared";
import type { DeflectResponse, SearchResponse, EntitySearchResponse } from "../types";

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

/** Palette search-as-you-type (spec 28) — key prefix + full text, RBAC-scoped. */
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
