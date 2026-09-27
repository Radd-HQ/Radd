import { api, ApiError, Entity } from "@radd/plugin-sdk";
import type { Project, ProjectSummary } from "./types";
import { projectQueryKeys as queryKeys } from "./query-keys";

const PROJECT_META = { entities: [Entity.project, Entity.role, Entity.team, Entity.group, Entity.member, Entity.accessGrant] };

export const projectsQuery = () =>
  ({
    queryKey: queryKeys.projects,
    meta: PROJECT_META,
    queryFn: ({ signal }: { signal: AbortSignal }) => api.get<Project[]>("/projects", { signal }),
  });

export const PROJECTS_PAGE_SIZE = 50;

export const projectSummaryQuery = () => ({
  queryKey: queryKeys.projectSummary,
  meta: PROJECT_META,
  staleTime: 30_000,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<ProjectSummary>("/projects/summary", { signal }),
});

export const projectsPageQuery = (
  q = "", page = 0, hideRelated = false, permission: string = "",
) => ({
  queryKey: queryKeys.projectsPage(q.trim(), page, hideRelated, permission),
  meta: PROJECT_META,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getPaged<Project>("/projects", { signal, query: {
    q: q.trim(), limit: String(PROJECTS_PAGE_SIZE), offset: String(page * PROJECTS_PAGE_SIZE),
    hide_related: String(hideRelated), permission: permission || undefined,
  } }),
});

async function readProject(path: string, signal: AbortSignal): Promise<Project | null> {
  try { return await api.get<Project>(path, { signal }); }
  catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export const projectByIdQuery = (id: string) => ({
  queryKey: queryKeys.projectById(id),
  meta: { ...PROJECT_META, projectId: id || undefined },
  queryFn: ({ signal }: { signal: AbortSignal }) => readProject(`/projects/${encodeURIComponent(id)}`, signal),
  enabled: Boolean(id),
  staleTime: 30_000,
});

export const projectByKeyQuery = (key: string) => ({
  queryKey: queryKeys.projectByKey(key),
  meta: PROJECT_META,
  queryFn: ({ signal }: { signal: AbortSignal }) => readProject(`/projects/by-key/${encodeURIComponent(key.toUpperCase())}`, signal),
  enabled: Boolean(key),
});

