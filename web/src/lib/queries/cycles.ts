/** Cycles (+ series/stats) and releases. */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiCyclePath,
  apiCycleStatsPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  Cycle,
  CycleSeries,
  CycleStats,
  CycleStatusValue,
  Item,
  Release,
} from "../types";

/** All cycles (spec 18); optional `status` filter (derived server-side). */
export const cyclesQuery = (status?: CycleStatusValue) =>
  queryOptions({
    queryKey: queryKeys.cycles(status),
    meta: entityMeta(Entity.cycle),
    queryFn: ({ signal }) => api.get<Cycle[]>(ApiPath.cycles, { signal, query: { status } }),
  });

export const CYCLES_PAGE_SIZE = 50;
export const cyclesPageQuery = (
  q = "", page = 0, status?: CycleStatusValue, includeCompleted = true, excludeId = "", datedOnly = false,
) => queryOptions({
  queryKey: queryKeys.cyclesPage(q.trim(), page, status, includeCompleted, excludeId, datedOnly),
  meta: entityMeta(Entity.cycle, Entity.team, Entity.role),
  queryFn: ({ signal }) => api.getPaged<Cycle>(ApiPath.cycles, { signal, query: {
    q: q.trim(), limit: String(CYCLES_PAGE_SIZE), offset: String(page * CYCLES_PAGE_SIZE),
    status, include_completed: String(includeCompleted), exclude_id: excludeId || undefined,
    dated_only: String(datedOnly),
  } }),
});

/** Prefer an active dated cycle, then the most recent dated cycle. The server
 * chooses from the whole visible catalog before limiting the result. */
export const defaultBurnupCycleQuery = () => queryOptions({
  queryKey: ["cycles", "default-burnup"] as const,
  meta: entityMeta(Entity.cycle, Entity.team, Entity.role),
  queryFn: ({ signal }) => api.get<Cycle[]>(ApiPath.cycles, { signal,
    query: { limit: "1", dated_only: "true", recent_first: "true" } }),
});

export const cycleSummaryQuery = (q = "") => queryOptions({
  queryKey: queryKeys.cycleSummary(q.trim()),
  meta: entityMeta(Entity.cycle, Entity.team, Entity.role),
  queryFn: ({ signal }) => api.get<Partial<Record<CycleStatusValue, number>>>(`${ApiPath.cycles}/summary`, {
    signal, query: { q: q.trim() },
  }),
});

/** A single cycle (spec 18) — the cycle items page reads its dates/goal here. */
export const cycleQuery = (cycleId: string) =>
  queryOptions({
    queryKey: queryKeys.cycle(cycleId),
    meta: entityMeta(Entity.cycle),
    queryFn: ({ signal }) => api.get<Cycle>(apiCyclePath(cycleId), { signal }),
  });

export const CYCLE_ITEMS_PAGE_SIZE = 50;

/** One cycle item window; every filter is applied before the server pages. */
export const cycleItemsQuery = (cycleId: string, page = 0, q = "", assigneeId = "", teamId = "") =>
  queryOptions({
    queryKey: ["cycleItems", cycleId, { page, q, assigneeId, teamId }] as const,
    queryFn: ({ signal }) => api.get<Item[]>(ApiPath.items, { signal, query: {
      cycle_id: cycleId, q: q || undefined, assignee_id: assigneeId || undefined,
      team_id: teamId || undefined, limit: String(CYCLE_ITEMS_PAGE_SIZE),
      offset: String(page * CYCLE_ITEMS_PAGE_SIZE),
    } }),
    meta: entityMeta(Entity.item),
  });

/** Recurring cycle series (per-label auto-provisioning config). */
export const cycleSeriesPageQuery = (q = "", page = 0) =>
  queryOptions({
    queryKey: queryKeys.cycleSeriesPage(q.trim(), page),
    meta: entityMeta(Entity.cycleSeries, Entity.role),
    queryFn: ({ signal }) => api.getPaged<CycleSeries>("/cycle-series", { signal, query: {
      q: q.trim(), limit: String(CYCLES_PAGE_SIZE), offset: String(page * CYCLES_PAGE_SIZE),
    } }),
  });

/** Cycle-page header metrics; filters mirror the page's list filters.
 * `projectId` scopes a cycle to one project's slice — project-scoped surfaces
 * MUST pass it or their handles show other projects' totals (cycles span
 * projects). */
export const cycleStatsQuery = (
  cycleId: string,
  assigneeId?: string,
  teamId?: string,
  projectId?: string,
  q?: string,
) =>
  queryOptions({
    queryKey: [
      "cycle-stats",
      cycleId,
      assigneeId ?? null,
      teamId ?? null,
      projectId ?? null,
      q ?? "",
    ] as const,
    queryFn: ({ signal }) =>
      api.get<CycleStats>(apiCycleStatsPath(cycleId), {
        signal,
        query: { assignee_id: assigneeId, team_id: teamId, project_id: projectId, q },
      }),
    meta: entityMeta(Entity.item, Entity.cycle, Entity.worklog), // item mutations change the counts/time totals
    placeholderData: keepPreviousData,
  });

/** Per-project releases (spec 18); create/manage requires project.manage. */
export const releasesQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.releases(projectId),
    queryFn: ({ signal }) => api.get<Release[]>(ApiPath.releases, { signal, query: { project_id: projectId } }),
  });
