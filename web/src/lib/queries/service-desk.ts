/** Service desk: canned responses + SLA policies/timers (specs 30/63). */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  SLA_BATCH_MAX_ITEMS,
  SLA_BATCH_REFETCH_MS,
  apiItemSlaPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  CannedResponse,
  ItemSla,
  SlaBatchResponse,
  SlaPolicy,
} from "../types";

/** Canned responses (spec 30) — readable by any member. */
export const cannedResponsesQuery = () =>
  queryOptions({
    queryKey: queryKeys.cannedResponses,
    queryFn: () => api.get<CannedResponse[]>(ApiPath.cannedResponses),
    meta: entityMeta(Entity.cannedResponse),
  });

/** One project's SLA policies (spec 30; project-level since spec 67). */
export const slaPoliciesQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.slaPolicies(projectId),
    queryFn: () =>
      api.get<SlaPolicy[]>(ApiPath.slaPolicies, { query: { project_id: projectId } }),
    meta: entityMeta(Entity.slaPolicy),
  });

/** Live SLA timer status for one item (spec 30; matched policy since spec 63). */
export const itemSlaQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemSla(itemId),
    queryFn: () => api.get<ItemSla>(apiItemSlaPath(itemId)),
    meta: entityMeta(Entity.slaPolicy, Entity.item),
    // Timers tick server-side; refresh the readout periodically while open.
    refetchInterval: SLA_BATCH_REFETCH_MS,
  });

/** Batch SLA timers for a surface's visible items (spec 63) — one POST per
 * loaded page, re-polled every minute. Callers gate with `enabled` so an
 * off slot fetches nothing; ids are sorted for a stable query key. */
export const slaBatchQuery = (itemIds: readonly string[]) => {
  const ids = [...itemIds].sort().slice(0, SLA_BATCH_MAX_ITEMS);
  return queryOptions({
    queryKey: queryKeys.slaBatch(ids),
    queryFn: () => api.post<SlaBatchResponse>(ApiPath.itemsSlaBatch, { item_ids: ids }),
    meta: entityMeta(Entity.slaPolicy, Entity.item),
    refetchInterval: SLA_BATCH_REFETCH_MS,
  });
};
