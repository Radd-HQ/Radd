/** Cycles (+ series/stats) and releases. */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  ITEMS_PAGE_LIMIT,
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
    queryFn: () => api.get<Cycle[]>(ApiPath.cycles, { query: { status } }),
  });

/** A single cycle (spec 18) — the cycle items page reads its dates/goal here. */
export const cycleQuery = (cycleId: string) =>
  queryOptions({
    queryKey: queryKeys.cycle(cycleId),
    queryFn: () => api.get<Cycle>(apiCyclePath(cycleId)),
  });

/** EVERY item in a cycle, via the server-side cycle filter — pages through GET
 * /items?cycle_id= so big cycles (300+) are complete (the old per-project
 * fetch-and-client-filter silently truncated at the page limit). */
export const cycleItemsQuery = (cycleId: string) =>
  queryOptions({
    queryKey: ["cycleItems", cycleId] as const,
    queryFn: async () => {
      const all: Item[] = [];
      for (let page = 0; page < 10; page++) {
        const batch = await api.get<Item[]>(ApiPath.items, {
          query: {
            cycle_id: cycleId,
            limit: String(ITEMS_PAGE_LIMIT),
            offset: String(page * ITEMS_PAGE_LIMIT),
          },
        });
        all.push(...batch);
        if (batch.length < ITEMS_PAGE_LIMIT) break;
      }
      return all;
    },
    meta: entityMeta(Entity.item),
  });

/** Recurring cycle series (per-label auto-provisioning config). */
export const cycleSeriesQuery = () =>
  queryOptions({
    queryKey: ["cycle-series"] as const,
    queryFn: () => api.get<CycleSeries[]>("/cycle-series"),
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
) =>
  queryOptions({
    queryKey: [
      "cycle-stats",
      cycleId,
      assigneeId ?? null,
      teamId ?? null,
      projectId ?? null,
    ] as const,
    queryFn: () =>
      api.get<CycleStats>(apiCycleStatsPath(cycleId), {
        query: { assignee_id: assigneeId, team_id: teamId, project_id: projectId },
      }),
    meta: entityMeta(Entity.item), // item mutations change the counts/time totals
    placeholderData: keepPreviousData,
  });

/** Per-project releases (spec 18); create/manage requires project.manage. */
export const releasesQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.releases(projectId),
    queryFn: () => api.get<Release[]>(ApiPath.releases, { query: { project_id: projectId } }),
  });
