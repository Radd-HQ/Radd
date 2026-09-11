/** Bounded saved-view/dashboard catalogs; direct links never depend on a page. */
import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import { ApiPath, apiViewPath } from "../constants";
import { queryKeys } from "./shared";
import type { Dashboard, View } from "../types";

export const SHARED_DIRECTORY_PAGE_SIZE = 50;
export interface ViewDirectoryScope {
  projectId?: string;
  includeGlobal?: boolean;
  globalOnly?: boolean;
  viewType?: string;
  excludeType?: string;
}
const scopeQuery = (scope: ViewDirectoryScope) => ({
  project_id: scope.projectId || undefined, include_global: String(scope.includeGlobal ?? true),
  global_only: String(scope.globalOnly ?? false), view_type: scope.viewType, exclude_type: scope.excludeType,
});
const viewsMeta = () => entityMeta(Entity.view, Entity.project, Entity.role, Entity.team, Entity.member, Entity.group, Entity.accessGrant);
const dashboardsMeta = () => entityMeta(Entity.dashboard, Entity.project, Entity.role, Entity.team, Entity.member, Entity.group, Entity.accessGrant);

export const viewQuery = (id: string) => queryOptions({
  queryKey: [...queryKeys.viewById(id), "definition"],
  queryFn: ({ signal }) => api.get<View>(apiViewPath(id), { signal, query: { include_shares: "false" } }),
  enabled: Boolean(id), retry: false, meta: viewsMeta(),
});

export const viewsPageQuery = (scope: ViewDirectoryScope = {}, q = "", page = 0, limit = SHARED_DIRECTORY_PAGE_SIZE) => {
  const filters = scopeQuery(scope);
  return queryOptions({
    queryKey: [...queryKeys.viewsPage(filters, q.trim(), page, limit), "definitions"],
    queryFn: ({ signal }) => api.getPaged<View>(ApiPath.views, { signal, query: {
      ...filters, include_shares: "false", q: q.trim(), limit: String(limit), offset: String(page * limit),
    } }), meta: viewsMeta(),
  });
};

export const dashboardsPageQuery = (q = "", page = 0) => queryOptions({
  queryKey: [...queryKeys.dashboardsPage(q.trim(), page), "definitions"],
  queryFn: ({ signal }) => api.getPaged<Dashboard>(ApiPath.dashboards, { signal, query: {
    include_shares: "false", q: q.trim(), limit: String(SHARED_DIRECTORY_PAGE_SIZE), offset: String(page * SHARED_DIRECTORY_PAGE_SIZE),
  } }), meta: dashboardsMeta(),
});

export const dashboardSummaryQuery = () => queryOptions({
  queryKey: queryKeys.dashboardSummary,
  queryFn: ({ signal }) => api.get<{ total: number }>(`${ApiPath.dashboards}/summary`, { signal }),
  meta: dashboardsMeta(),
});
