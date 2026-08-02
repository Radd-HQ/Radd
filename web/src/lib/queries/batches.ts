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
    queryFn: () => api.post<RollupResponse>(ApiPath.itemsRollup, { item_ids: ids }),
    meta: entityMeta(Entity.item),
  });
};

/** Batched estimate/logged seconds for the roadmap's auto-schedule durations
 * (spec 78) — fetched lazily when the roadmap mounts with timelogging enabled;
 * failures fall back to all-default durations, so callers never toast on it. */
export const timelogBatchQuery = (itemIds: readonly string[]) => {
  const ids = [...itemIds].sort().slice(0, TIMELOG_BATCH_MAX_ITEMS);
  return queryOptions({
    queryKey: queryKeys.timelogBatch(ids),
    queryFn: () => api.post<TimelogBatchResponse>(ApiPath.itemsTimelogBatch, { item_ids: ids }),
    meta: entityMeta(Entity.worklog, Entity.item),
    retry: false,
  });
};

/** Chunked timelog batch for surfaces whose id set may exceed one POST's cap
 * (the roadmap progress tints): one queryFn fans out sequential
 * ≤TIMELOG_BATCH_MAX_ITEMS requests and merges the maps. Same quiet-degrade
 * contract as `timelogBatchQuery` — retry: false, callers never toast on it. */
export const timelogBatchChunkedQuery = (itemIds: readonly string[]) => {
  const ids = [...itemIds].sort();
  return queryOptions({
    queryKey: queryKeys.timelogBatch(ids),
    queryFn: async () => {
      const merged: TimelogBatchResponse = {};
      for (let start = 0; start < ids.length; start += TIMELOG_BATCH_MAX_ITEMS) {
        const chunk = ids.slice(start, start + TIMELOG_BATCH_MAX_ITEMS);
        Object.assign(
          merged,
          await api.post<TimelogBatchResponse>(ApiPath.itemsTimelogBatch, { item_ids: chunk }),
        );
      }
      return merged;
    },
    meta: entityMeta(Entity.worklog, Entity.item),
    retry: false,
  });
};
