import { api, Entity } from "@radd/plugin-sdk";
import type { Cycle, CycleStatusValue } from "./types";
import { cycleDirectoryKeys as queryKeys } from "./query-keys";

const CYCLE_META = { entities: [Entity.cycle, Entity.team, Entity.role, Entity.project, Entity.group, Entity.member, Entity.accessGrant] };

export const CYCLES_PAGE_SIZE = 50;
export const cyclesPageQuery = (
  q = "", page = 0, status?: CycleStatusValue, includeCompleted = true, excludeId = "", datedOnly = false, projectId = "",
) => ({
  queryKey: queryKeys.cyclesPage(q.trim(), page, status, includeCompleted, excludeId, datedOnly, projectId),
  meta: CYCLE_META,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getPaged<Cycle>("/cycles", { signal, query: {
    q: q.trim(), limit: String(CYCLES_PAGE_SIZE), offset: String(page * CYCLES_PAGE_SIZE),
    status, include_completed: String(includeCompleted), exclude_id: excludeId || undefined,
    dated_only: String(datedOnly), project_id: projectId || undefined,
  } }),
});


/** A single cycle (spec 18) — the cycle items page reads its dates/goal here. */
export const cycleQuery = (cycleId: string) =>
  ({
    queryKey: queryKeys.cycle(cycleId),
    meta: CYCLE_META,
    queryFn: ({ signal }: { signal: AbortSignal }) => api.get<Cycle>(`/cycles/${encodeURIComponent(cycleId)}`, { signal }),
  });

