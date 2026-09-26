/**
 * The dashboards plugin's transport: every `/dashboards` path and query key lives here, under the
 * plugin's own name, so the host names none of them (RADD-1393). The host's nav facts read
 * `dashboardSummaryQuery` through this package's `./queries` export.
 */
import { api } from "@radd/plugin-sdk";
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
export const DASHBOARD_META = { entities: ["dashboard", "project", "role", "team", "member", "group", "accessGrant"] };

export const SIDEBAR_PAGE_SIZE = 50;

export const dashboardsPageQuery = (q = "", page = 0, pageSize = SIDEBAR_PAGE_SIZE) => ({
  queryKey: dashboardKeys.page(q.trim(), page),
  meta: DASHBOARD_META,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getPaged<Dashboard>(DASHBOARDS_PATH, { signal, query: {
    include_shares: "false", q: q.trim(), limit: String(pageSize), offset: String(page * pageSize),
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
