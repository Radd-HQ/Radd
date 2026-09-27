/** Every `/dashboards` path and query key; the host's nav facts read `dashboardSummaryQuery` via `./queries`. */
import { api, Entity } from "@radd/plugin-sdk";
import type { Dashboard, DashboardWidget } from "./types";

export const DASHBOARDS_PATH = "/dashboards";
export const dashboardPath = (id: string) => `${DASHBOARDS_PATH}/${id}`;
export const dashboardWidgetsPath = (id: string) => `${dashboardPath(id)}/widgets`;
export const dashboardWidgetPath = (id: string, widgetId: string) => `${dashboardWidgetsPath(id)}/${widgetId}`;
export const MY_WORK_PATH = `${DASHBOARDS_PATH}/my-work`;

/** Every dashboards query keys under the plugin's name, so a withdrawal drops them together. */
export const dashboardKeys = {
  page: (q: string, page: number) => ["dashboards", "page", { q, page }] as const,
  summary: ["dashboards", "summary"] as const,
  definition: (id: string) => ["dashboards", "definition", id] as const,
  myWork: ["dashboards", "my-work", "widgets"] as const,
  activity: (project: string, start: string, end: string) => ["dashboards", "my-work", "activity", { project, start, end }] as const,
};

/** A dashboard is readable through its owner, grants, roles and teams — any of them moves it. */
const DASHBOARD_META = { entities: [Entity.dashboard, Entity.project, Entity.role, Entity.team, Entity.member, Entity.group, Entity.accessGrant] };

export const SIDEBAR_PAGE_SIZE = 50;

export const dashboardsPageQuery = (q: string, page: number, pageSize: number) => ({
  queryKey: dashboardKeys.page(q, page),
  meta: DASHBOARD_META,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getPaged<Dashboard>(DASHBOARDS_PATH, { signal, query: {
    include_shares: "false", q, limit: String(pageSize), offset: String(page * pageSize),
  } }),
});

/** How many dashboards the reader can see — the shell's nav facts decide the section on it. */
export const dashboardSummaryQuery = () => ({
  queryKey: dashboardKeys.summary,
  meta: DASHBOARD_META,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<{ total: number }>(`${DASHBOARDS_PATH}/summary`, { signal }),
});

/** One dashboard's full definition incl. widgets + per-actor can_edit/can_manage.
 * `retry: false` — an invisible dashboard 404s and should say so immediately. */
export const dashboardQuery = (id: string) => ({
  queryKey: dashboardKeys.definition(id),
  meta: DASHBOARD_META,
  retry: false,
  enabled: id !== "",
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<Dashboard>(dashboardPath(id), { signal, query: { include_shares: "false" } }),
});

/** My Work's layout: the person's saved widgets, else the suggested defaults. */
export const myWorkQuery = () => ({
  queryKey: dashboardKeys.myWork,
  retry: false,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<DashboardWidget[]>(`${MY_WORK_PATH}/widgets`, { signal }),
});
