/** Saved views, view counts, and SLQ item queries. */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { allRelationRows } from "../pagination";
import { api } from "../api";
import { Entity, entityMeta, projectEntityMeta } from "@radd/plugin-sdk";
import {
  ApiPath,
  ITEMS_PAGE_LIMIT,
  ROADMAP_MEMBERS_LIMIT,
  ROADMAP_TRAY_PAGE_LIMIT,
  VIEW_COUNTS_MAX_VIEWS,
  VIEW_COUNTS_REFETCH_MS,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  CardLayoutPreset,
  Item,
  ItemIds,
  View,
  ViewListSurface,
} from "../types";

/** Batched view counts for a view type's own sidebar section: ONE POST /views/counts, re-polled
 *  every minute. Ids sorted for a stable key, sliced to the server's cap; unknown ids are omitted. */
export const viewCountsQuery = (viewIds: readonly string[], extraQ?: string) => {
  const ids = [...viewIds].sort().slice(0, VIEW_COUNTS_MAX_VIEWS);
  return queryOptions({
    queryKey: queryKeys.viewCounts(ids, extraQ),
    queryFn: ({ signal }) =>
      api.post<Record<string, number>>(ApiPath.viewCounts, {
        view_ids: ids,
        extra_q: extraQ || undefined,
      }, { signal }),
    // Counts move when items move (and when view queries are edited).
    meta: entityMeta(Entity.item, Entity.view),
    refetchInterval: VIEW_COUNTS_REFETCH_MS,
  });
};

/** The shared card-layout preset library (spec 109) — readable by any member;
 * the card designer's preset picker. */
export const cardLayoutPresetsQuery = () =>
  queryOptions({
    queryKey: queryKeys.cardLayoutPresets,
    queryFn: ({ signal }) => api.get<CardLayoutPreset[]>(ApiPath.cardLayoutPresets, { signal }),
    meta: entityMeta(Entity.cardLayoutPreset),
  });

/** A query's visible-match total alone (My Work's section counts). Tagged `item`
 * so realtime item churn keeps the number live; SLQ 422s don't retry. */
export const itemsCountQuery = (scope: Record<string, string>, q: string) =>
  queryOptions({
    queryKey: queryKeys.itemsCount(scope, q),
    meta: projectEntityMeta(scope.project_id, Entity.item),
    queryFn: ({ signal }) =>
      api.get<{ total: number }>(ApiPath.itemsCount, {
        signal,
        query: { ...scope, q: q || undefined },
      }),
    retry: false,
    staleTime: 15_000,
  });

/** Ids + true count of everything matching a view's filter (spec 68) — the
 *  "select all N matching" seam; ids are capped server-side. */
export const itemIdsQuery = (queryString: string) =>
  queryOptions({
    queryKey: queryKeys.itemIds(queryString),
    meta: entityMeta(Entity.item),
    queryFn: ({ signal }) =>
      api.get<ItemIds>(queryString ? `${ApiPath.itemsIds}?${queryString}` : ApiPath.itemsIds, { signal }),
    staleTime: 15_000,
  });

/** ONE page of a view's items: the page is part of the key, and `placeholderData` keeps the old page
 *  on screen while the next loads. Roadmaps use the infinite variant below. */
export const pagedViewItemsQuery = (
  view: Pick<View, "id" | "query_string"> | undefined,
  page: number,
  // RADD-1154: the page size follows the viewport (`useItemsPageLimit`); it is
  // part of the key, so a rotation refetches the right page.
  limit: number = ITEMS_PAGE_LIMIT,
  // RADD-1396: a plugin view type on the host's list names its own rows (the `/items` paging
  // contract, in the plugin's order) and how often they go stale; absent = `/items`.
  surface?: Pick<ViewListSurface, "rows_path" | "refresh_seconds"> | null,
) => {
  const rowsPath = surface?.rows_path || ApiPath.items;
  return queryOptions({
    queryKey: [...queryKeys.viewItemsPage(view?.id ?? "", view?.query_string ?? "", page, limit), rowsPath],
    refetchInterval: surface?.refresh_seconds ? surface.refresh_seconds * 1000 : false,
    meta: projectEntityMeta(new URLSearchParams(view?.query_string).get("project_id"), Entity.item),
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      api.get<Item[]>(`${rowsPath}?${view?.query_string ?? ""}`, {
        signal,
        query: {
          limit: String(limit),
          offset: String((page - 1) * limit),
        },
      }),
  });
};

/** A saved view's items, streamed page by page (roadmaps). The view's `query_string` is appended
 *  VERBATIM (spec 08: no client-side translation); the view-page mutations patch this paged shape. */
export const infiniteViewItemsQuery = (view: Pick<View, "id" | "query_string"> | undefined) => ({
  queryKey: queryKeys.viewItems(view?.id ?? "", view?.query_string ?? ""),
  meta: projectEntityMeta(new URLSearchParams(view?.query_string).get("project_id"), Entity.item),
  initialPageParam: 0,
  queryFn: ({ signal, pageParam }: { signal: AbortSignal; pageParam: number }) =>
    api.get<Item[]>(`${ApiPath.items}?${view?.query_string ?? ""}`, {
        signal,
      query: { limit: String(ITEMS_PAGE_LIMIT), offset: String(pageParam) },
    }),
  getNextPageParam: (lastPage: Item[], _all: Item[][], lastOffset: number) =>
    lastPage.length === ITEMS_PAGE_LIMIT ? lastOffset + ITEMS_PAGE_LIMIT : undefined,
});

/** The roadmap's Unscheduled tray: its own bounded, paged pool (the main roadmap fetch carries no
 *  unscheduled leaves). `q` arrives fully composed (view query + tray clause + chips + search). */
export const roadmapTrayItemsQuery = (
  viewId: string,
  q: string,
  projectId: string | null,
  page: number,
) =>
  queryOptions({
    queryKey: queryKeys.roadmapTray(viewId, q, projectId ?? "", page),
    meta: projectEntityMeta(projectId, Entity.item),
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      api.get<Item[]>(ApiPath.items, {
        signal,
        query: {
          q,
          project_id: projectId ?? undefined,
          limit: String(ROADMAP_TRAY_PAGE_LIMIT),
          offset: String((page - 1) * ROADMAP_TRAY_PAGE_LIMIT),
        },
      }),
  });

/** A roadmap view's curated member set, read through the item dialect's `roadmap` field (hydrated
 *  and item-RBAC-scoped); every page of it. */
export const roadmapMembersQuery = (viewId: string) =>
  queryOptions({
    queryKey: queryKeys.roadmapMembers(viewId),
    meta: entityMeta(Entity.item),
    queryFn: ({ signal }) =>
      allRelationRows<Item>(ApiPath.items, { q: `roadmap = "${viewId}"` }, signal, ROADMAP_MEMBERS_LIMIT),
    staleTime: 15_000,
  });

/** Items matching a COMMITTED ad-hoc SLQ query (one page at the API cap), fetched on Enter — live
 *  feedback is `slqValidateQuery`. A parse error is a 422, so `retry: false`. */
export const slqItemsQuery = (scope: Record<string, string>, q: string) =>
  queryOptions({
    queryKey: queryKeys.slqItems(scope, q),
    meta: projectEntityMeta(scope.project_id, Entity.item),
    queryFn: ({ signal }) =>
      api.get<Item[]>(ApiPath.items, {
        signal,
        query: { ...scope, q, limit: String(ITEMS_PAGE_LIMIT) },
      }),
    retry: false,
    staleTime: 15_000,
    // While a refined query fetches, keep showing the previous result set —
    // the probe surfaces "checking" (isFetching) so stale counts don't lie.
    placeholderData: keepPreviousData,
  });

/** Paged variant of `slqItemsQuery` for surfaces that render the result set
 *  directly (the list route) — offset Load-more past the first page. */
export const infiniteSlqItemsQuery = (scope: Record<string, string>, q: string) => ({
  // Distinct key from the flat `slqItemsQuery` — same key + different cache
  // shapes (Item[] vs InfiniteData) would corrupt each other.
  queryKey: ["slqItemsInfinite", { scope, q }] as const,
  meta: projectEntityMeta(scope.project_id, Entity.item),
  initialPageParam: 0,
  queryFn: ({ signal, pageParam }: { signal: AbortSignal; pageParam: number }) =>
    api.get<Item[]>(ApiPath.items, {
        signal,
      query: { ...scope, q, limit: String(ITEMS_PAGE_LIMIT), offset: String(pageParam) },
    }),
  getNextPageParam: (lastPage: Item[], _all: Item[][], lastOffset: number) =>
    lastPage.length === ITEMS_PAGE_LIMIT ? lastOffset + ITEMS_PAGE_LIMIT : undefined,
  retry: false,
  staleTime: 15_000,
});

/**
 * Live SLQ draft validation (spec 55): parse + compile ONLY — the server never
 * touches the items table, so this is safe to fire on every settled keystroke
 * even against huge projects. Valid -> {ok}; invalid -> 422 {detail, position}.
 */
export const slqValidateQuery = (
  projectId: string | null,
  q: string,
  dialect: string = ApiPath.items,
) =>
  queryOptions({
    queryKey: [...queryKeys.slqValidate(projectId, q), dialect],
    queryFn: ({ signal }) =>
      api.get<{ ok: boolean }>(`${dialect}/slq/validate`, {
        signal,
        query: { q, ...(projectId ? { project_id: projectId } : {}) },
      }),
    retry: false,
    // A draft's validity is stable — cache hard so backspace-retype is free.
    staleTime: 5 * 60_000,
  });
