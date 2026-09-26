/** What the builtin SLQ and saved-view widgets read — the owners' public endpoints, under this
 *  plugin's keys, tagged with the owners' entities so live updates refresh them. */
import { api, type Item } from "@radd/plugin-sdk";

const itemMeta = (projectId?: string) => ({ entities: ["item"], projectId: projectId || undefined });
/** How often a saved-view count re-polls (the sidebar's queue badges use the same minute). */
const VIEW_COUNT_REFETCH_MS = 60_000;

/** The big number of an slq_count widget. */
export const itemsCountQuery = (scope: Record<string, string>, q: string) => ({
  queryKey: ["dashboards", "widget", "count", scope, q] as const,
  meta: itemMeta(scope.project_id),
  retry: false,
  staleTime: 15_000,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    api.get<{ total: number }>("/items/count", { signal, query: { ...scope, q: q || undefined } }),
});

/** An slq_list widget's few compact rows, at the widget's own limit. */
export const itemsListQuery = (scope: Record<string, string>, q: string, limit: number) => ({
  queryKey: ["dashboards", "widget", "list", scope, q, limit] as const,
  meta: itemMeta(scope.project_id),
  retry: false,
  staleTime: 15_000,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    api.get<Item[]>("/items", { signal, query: { ...scope, q: q || undefined, limit: String(limit) } }),
});

/** One saved view's membership count; the server OMITS a view the reader cannot see. */
export const viewCountQuery = (viewId: string, extraQ?: string) => ({
  queryKey: ["dashboards", "widget", "view-count", viewId, extraQ ?? ""] as const,
  meta: { entities: ["item", "view"] },
  enabled: viewId !== "",
  refetchInterval: VIEW_COUNT_REFETCH_MS,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    api.post<Record<string, number>>("/views/counts", { view_ids: [viewId], extra_q: extraQ || undefined }, { signal }),
});

interface ViewRef {
  id: string;
  name: string;
  project_id: string | null;
}

export const viewQuery = (viewId: string) => ({
  queryKey: ["dashboards", "widget", "view", viewId] as const,
  meta: { entities: ["view", "project", "role", "team", "member", "group", "accessGrant"] },
  enabled: viewId !== "",
  retry: false,
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    api.get<ViewRef>(`/views/${viewId}`, { signal, query: { include_shares: "false" } }),
});

/** The key a project view's link needs. */
export const projectKeyQuery = (projectId: string) => ({
  queryKey: ["dashboards", "widget", "project", projectId] as const,
  meta: { entities: ["project"] },
  enabled: projectId !== "",
  retry: false,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<{ id: string; key: string }>(`/projects/${projectId}`, { signal }),
});
