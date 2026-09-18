/** Projects, states/transitions, screens, issue types, field writability, and membership. */

import { queryOptions } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Entity, entityMeta, projectEntityMeta, itemEntityMeta } from "../cache";
import {
  ApiPath,
  apiItemAllowedTransitionsPath,
  apiProjectContentPath,
  apiProjectTransitionsPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  AllowedTransitions,
  EffectiveScreen,
  IssueType,
  Project,
  ProjectContentSummary,
  ProjectSummary,
  PermissionValue,
  State,
  StateCategoryRow,
  Transition,
} from "../types";

export const projectsQuery = () =>
  queryOptions({
    queryKey: queryKeys.projects,
    meta: entityMeta(Entity.project),
    queryFn: ({ signal }) => api.get<Project[]>(ApiPath.projects, { signal }),
  });

/** Default context for a selector, without downloading its remaining choices. */
export const firstProjectQuery = () => queryOptions({
  queryKey: queryKeys.firstProject,
  meta: entityMeta(Entity.project, Entity.role),
  queryFn: ({ signal }) => api.get<Project[]>(ApiPath.projects, { signal, query: { limit: "1" } }),
});

export const PROJECTS_PAGE_SIZE = 50;

export const projectSummaryQuery = () => queryOptions({
  queryKey: queryKeys.projectSummary,
  meta: entityMeta(Entity.project, Entity.role, Entity.team, Entity.group, Entity.member, Entity.accessGrant),
  staleTime: 30_000,
  queryFn: ({ signal }) => api.get<ProjectSummary>(`${ApiPath.projects}/summary`, { signal }),
});

export const projectsPageQuery = (
  q = "", page = 0, hideRelated = false, permission: PermissionValue | "" = "",
) => queryOptions({
  queryKey: queryKeys.projectsPage(q.trim(), page, hideRelated, permission),
  meta: entityMeta(Entity.project, Entity.role),
  queryFn: ({ signal }) => api.getPaged<Project>(ApiPath.projects, { signal, query: {
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

export const projectByIdQuery = (id: string) => queryOptions({
  queryKey: queryKeys.projectById(id),
  meta: projectEntityMeta(id, Entity.project, Entity.role, Entity.team, Entity.group,
    Entity.member, Entity.accessGrant),
  queryFn: ({ signal }) => readProject(`${ApiPath.projects}/${encodeURIComponent(id)}`, signal),
  enabled: Boolean(id),
  staleTime: 30_000,
});

export const projectByKeyQuery = (key: string) => queryOptions({
  queryKey: queryKeys.projectByKey(key),
  meta: entityMeta(Entity.project, Entity.role),
  queryFn: ({ signal }) => readProject(`${ApiPath.projects}/by-key/${encodeURIComponent(key.toUpperCase())}`, signal),
  enabled: Boolean(key),
});

/** RADD-1174: the delete dialog's numbers + blockers. Never stale — it is
 * read at the moment of the decision. */
export const projectContentQuery = (projectId: string) =>
  queryOptions({
    queryKey: [...queryKeys.projectById(projectId), "content"] as const,
    queryFn: ({ signal }) => api.get<ProjectContentSummary>(apiProjectContentPath(projectId), { signal }),
    staleTime: 0,
  });

export const statesQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.states(projectId),
    meta: projectEntityMeta(projectId, Entity.project),
    queryFn: ({ signal }) => api.get<State[]>(ApiPath.states, { signal, query: { project_id: projectId } }),
    staleTime: 60_000,
  });

/** State categories (RADD-854) — the user-owned vocabulary tier; any member
 * may read, instance admins manage. */
export const stateCategoriesQuery = () =>
  queryOptions({
    queryKey: queryKeys.stateCategories,
    meta: entityMeta(Entity.project),
    queryFn: ({ signal }) => api.get<StateCategoryRow[]>(ApiPath.stateCategories, { signal }),
    staleTime: 60_000,
  });

/** Every readable project's states — the cross-project state-drag resolver on
 * all-projects board views (buckets are name-keyed there). */
export const allStatesQuery = () =>
  queryOptions({
    queryKey: queryKeys.allStates,
    meta: entityMeta(Entity.project),
    queryFn: ({ signal }) => api.get<State[]>(ApiPath.states, { signal }),
    staleTime: 60_000,
  });

/** A project's ordered transition rows (spec 61) — the settings editor's source. */
export const transitionsQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.transitions(projectId),
    queryFn: ({ signal }) => api.get<Transition[]>(apiProjectTransitionsPath(projectId), { signal }),
    meta: entityMeta(Entity.transition),
  });

/** Per-target allow/deny for an item's state pickers (spec 61). Tagged with
 * `item` so every item mutation refreshes the allowed set automatically. */
export const allowedTransitionsQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.allowedTransitions(itemId),
    queryFn: ({ signal }) => api.get<AllowedTransitions>(apiItemAllowedTransitionsPath(itemId), { signal }),
    meta: itemEntityMeta(itemId, Entity.transition, Entity.item, Entity.role, Entity.team,
      Entity.group, Entity.member, Entity.accessGrant),
  });

/** The builtin names + custom field keys the current user CAN'T write in a project (spec 92) — so
 *  editors disable up front instead of erroring on save. Per-(actor, project), cached. */
export const fieldWritabilityQuery = (projectId: string | null | undefined) =>
  queryOptions({
    queryKey: ["field-writability", projectId ?? ""] as const,
    meta: entityMeta(Entity.field, Entity.role, Entity.team, Entity.group, Entity.member, Entity.accessGrant),
    queryFn: ({ signal }) =>
      api.get<{ readonly_fields: string[] }>("/fields/writable", {
        signal,
        query: { project_id: projectId ?? "" },
      }),
    enabled: Boolean(projectId),
    staleTime: 60_000,
  });

export const issueTypesQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.issueTypes(projectId),
    queryFn: ({ signal }) =>
      api.get<IssueType[]>(ApiPath.issueTypes, { signal, query: { project_id: projectId } }),
    staleTime: 60_000,
  });

/** The resolved field layout for an item's (project, issue-type) — drives the
 * issue view's rail (spec 53 screens). issueTypeId null = the project default. */
export const effectiveScreenQuery = (projectId: string, issueTypeId: string | null) =>
  queryOptions({
    queryKey: queryKeys.effectiveScreen(projectId, issueTypeId),
    queryFn: ({ signal }) =>
      api.get<EffectiveScreen>(ApiPath.screensEffective, {
        signal,
        query: issueTypeId
          ? { project_id: projectId, issue_type_id: issueTypeId }
          : { project_id: projectId },
      }),
    staleTime: 60_000,
  });
