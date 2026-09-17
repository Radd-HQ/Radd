/** Saved views, dashboards, view counts, and SLQ item queries. */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { allRelationRows } from "../pagination";
import { api } from "../api";
import { Entity, entityMeta, projectEntityMeta } from "../cache";
import {
  ApiPath,
  ITEMS_PAGE_LIMIT,
  ROADMAP_MEMBERS_LIMIT,
  ROADMAP_TRAY_PAGE_LIMIT,
  VIEW_COUNTS_MAX_VIEWS,
  VIEW_COUNTS_REFETCH_MS,
  apiDashboardPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  CardLayoutPreset,
  Dashboard,
  Item,
  ItemIds,
  View,
} from "../types";

/**
 * Batched view membership counts (spec 64) — the sidebar queue badges: ONE
 * POST /views/counts per sidebar, re-polled every minute. Invisible/unknown
 * ids are omitted by the server (never errored); ids are sorted for a stable
 * key and sliced to the backend's 50-view cap.
 */
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

/** One dashboard's full definition incl. widgets + per-actor can_edit/can_manage.
 * `retry: false` — an invisible dashboard 404s and should say so immediately. */
export const dashboardQuery = (dashboardId: string) =>
  queryOptions({
    queryKey: [...queryKeys.dashboard(dashboardId), "definition"],
    meta: entityMeta(Entity.dashboard, Entity.project, Entity.role, Entity.member, Entity.team, Entity.group, Entity.accessGrant),
    queryFn: ({ signal }) => api.get<Dashboard>(apiDashboardPath(dashboardId), { signal, query: { include_shares: "false" } }),
    retry: false,
  });

/** slq_count widgets (spec 75): the visible-match total alone. Tagged `item`
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

/** slq_list widgets (spec 75): a few compact rows at the widget's own limit
 * (distinct from `slqItemsQuery`, which always fetches a full page). */
export const slqListItemsQuery = (scope: Record<string, string>, q: string, limit: number) =>
  queryOptions({
    queryKey: queryKeys.slqListItems(scope, q, limit),
    meta: projectEntityMeta(scope.project_id, Entity.item),
    queryFn: ({ signal }) =>
      api.get<Item[]>(ApiPath.items, {
        signal,
        query: { ...scope, q: q || undefined, limit: String(limit) },
      }),
    retry: false,
    staleTime: 15_000,
  });

/**
 * Items of a saved view: the view's pre-composed `query_string` is appended
 * VERBATIM (spec 08 contract — zero client-side translation), plus the page
 * limit the plain board/list also use. Accepts undefined while the view is
 * still resolving — pair with `enabled: Boolean(view)`.
 */
/**
 * A saved view's items, paged (spec 55): the view's `query_string` (SLQ `q=` +
 * scope) does the filtering/ordering server-side; pages of the API cap with
 * offset-based Load more. Same cache key as the old single-page query — the
 * view-page mutations (`item-mutations.ts`) patch this paged shape.
 */
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

/**
 * ONE page of a view's items (pagination wave): classic paged
 * navigation — the page is part of the key, `placeholderData` keeps the old
 * page on screen while the next loads. Roadmaps keep the infinite variant
 * below (they auto-stream their whole match set).
 */
export const pagedViewItemsQuery = (
  view: (Pick<View, "id" | "query_string"> & Partial<Pick<View, "view_type">>) | undefined,
  page: number,
  // RADD-1154: the page size follows the viewport (`useItemsPageLimit`); it is
  // part of the key, so a rotation refetches the right page.
  limit: number = ITEMS_PAGE_LIMIT,
) =>
  queryOptions({
    queryKey: [...queryKeys.viewItemsPage(view?.id ?? "", view?.query_string ?? "", page, limit), view?.view_type],
    refetchInterval: view?.view_type === "queue" ? 60_000 : false,
    meta: projectEntityMeta(new URLSearchParams(view?.query_string).get("project_id"), Entity.item),
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      api.get<Item[]>(`${view?.view_type === "queue" ? "/sla-queue-items" : ApiPath.items}?${view?.query_string ?? ""}`, {
        signal,
        query: {
          limit: String(limit),
          offset: String((page - 1) * limit),
        },
      }),
  });

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

/**
 * The roadmap's Unscheduled tray (perf wave; classic pages since the
 * pagination wave): its own bounded pool — the main roadmap fetch no longer
 * carries unscheduled leaves. `q` arrives fully composed (view query + tray
 * clause + chips + search).
 */
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

/**
 * A roadmap view's curated member set (roadmap wave) — read through the item
 * dialect's registry-contributed `roadmap` field, so the result is hydrated
 * AND item-RBAC-scoped. Fetch every page of this curated relation.
 */
export const roadmapMembersQuery = (viewId: string) =>
  queryOptions({
    queryKey: queryKeys.roadmapMembers(viewId),
    meta: entityMeta(Entity.item),
    queryFn: ({ signal }) =>
      allRelationRows<Item>(ApiPath.items, { q: `roadmap = "${viewId}"` }, signal, ROADMAP_MEMBERS_LIMIT),
    staleTime: 15_000,
  });

/**
 * Items matching a COMMITTED ad-hoc SLQ query in a scope (spec 10 `q=` param):
 * one page at the API cap — the page filter bars' match set (spec 55: fetched
 * on Enter, never per keystroke — live feedback is `slqValidateQuery`). A parse
 * error rejects with a 422 `{detail, position}` payload (`slqErrorOf` in
 * lib/slq.ts), so `retry: false` — retrying a parse error is noise.
 */
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
