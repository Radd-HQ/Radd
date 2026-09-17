import { useQueries } from "@tanstack/react-query";
import { useStableItemBatches } from "../useStableItemBatches";
/** Batched item-card data: epic rollups (spec 76) + timelog seconds (spec 78). */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  ROLLUP_MAX_ITEMS,
  TIMELOG_BATCH_MAX_ITEMS,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  RollupResponse,
  TimelogBatchResponse,
} from "../types";

/** Batched epic-progress rollup for a surface's visible epic items (spec 76) —
 * one POST per loaded page; ids sorted for a stable key. Item mutations
 * invalidate it via the Entity.item meta (progress moves with state changes). */
export const rollupBatchQuery = (itemIds: readonly string[]) => {
  const ids = [...itemIds].sort().slice(0, ROLLUP_MAX_ITEMS);
  return queryOptions({
    queryKey: queryKeys.rollupBatch(ids),
    queryFn: ({ signal }) => api.post<RollupResponse>(ApiPath.itemsRollup, { item_ids: ids }, { signal }),
    meta: entityMeta(Entity.item),
  });
};

/** Batched estimate/logged seconds (spec 78): one queryFn fans out sequential
 * ≤TIMELOG_BATCH_MAX_ITEMS requests and merges the maps. Quiet-degrade
 * contract — retry: false, failures fall back to defaults, callers never
 * toast on it. */
export const timelogBatchChunkedQuery = (itemIds: readonly string[]) => {
  const ids = [...itemIds].sort();
  return queryOptions({
    queryKey: queryKeys.timelogBatch(ids),
    queryFn: async ({ signal }) => {
      const merged: TimelogBatchResponse = {};
      for (let start = 0; start < ids.length; start += TIMELOG_BATCH_MAX_ITEMS) {
        const chunk = ids.slice(start, start + TIMELOG_BATCH_MAX_ITEMS);
        Object.assign(
          merged,
          await api.post<TimelogBatchResponse>(ApiPath.itemsTimelogBatch, { item_ids: chunk }, { signal }),
        );
      }
      return merged;
    },
    meta: entityMeta(Entity.worklog, Entity.item),
    retry: false,
  });
};

/** Appending items does not refetch previous time batches. Existing mutation and
 * worklog invalidations still refresh each active chunk through entity metadata. */
export function useTimelogBatches(ids: readonly string[], enabled: boolean) {
  const batches = useStableItemBatches(enabled ? ids : [], TIMELOG_BATCH_MAX_ITEMS);
  const queries = useQueries({queries: batches.map(batch => timelogBatchChunkedQuery(batch))});
  return enabled ? Object.assign({}, ...queries.map(q => q.data ?? {})) as TimelogBatchResponse : undefined;
}
