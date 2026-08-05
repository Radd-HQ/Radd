/** Projects, states/transitions, screens, issue types, field writability, and membership. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiItemAllowedTransitionsPath,
  apiProjectMembersPath,
  apiProjectTeamsPath,
  apiProjectTransitionsPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  AllowedTransitions,
  EffectiveScreen,
  IssueType,
  Project,
  ProjectMember,
  ProjectTeam,
  State,
  StateCategoryRow,
  Transition,
} from "../types";

export const projectsQuery = () =>
  queryOptions({
    queryKey: queryKeys.projects,
    queryFn: () => api.get<Project[]>(ApiPath.projects),
  });

export const statesQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.states(projectId),
    queryFn: () => api.get<State[]>(ApiPath.states, { query: { project_id: projectId } }),
    staleTime: 60_000,
  });

/** State categories (RADD-854) — the user-owned vocabulary tier; any member
 * may read, instance admins manage. */
export const stateCategoriesQuery = () =>
  queryOptions({
    queryKey: queryKeys.stateCategories,
    queryFn: () => api.get<StateCategoryRow[]>(ApiPath.stateCategories),
    staleTime: 60_000,
  });

/** Every readable project's states — the cross-project state-drag resolver on
 * all-projects board views (buckets are name-keyed there). */
export const allStatesQuery = () =>
  queryOptions({
    queryKey: queryKeys.allStates,
    queryFn: () => api.get<State[]>(ApiPath.states),
    staleTime: 60_000,
  });

/** A project's ordered transition rows (spec 61) — the settings editor's source. */
export const transitionsQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.transitions(projectId),
    queryFn: () => api.get<Transition[]>(apiProjectTransitionsPath(projectId)),
    meta: entityMeta(Entity.transition),
  });

/** Per-target allow/deny for an item's state pickers (spec 61). Tagged with
 * `item` so every item mutation refreshes the allowed set automatically. */
export const allowedTransitionsQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.allowedTransitions(itemId),
    queryFn: () => api.get<AllowedTransitions>(apiItemAllowedTransitionsPath(itemId)),
    meta: entityMeta(Entity.transition, Entity.item),
  });

/** The builtin names + custom field keys the current user CAN'T write in a project (spec 92) — so
 *  editors disable up front instead of erroring on save. Per-(actor, project), cached. */
export const fieldWritabilityQuery = (projectId: string | null | undefined) =>
  queryOptions({
    queryKey: ["field-writability", projectId ?? ""] as const,
    queryFn: () =>
      api.get<{ readonly_fields: string[] }>("/fields/writable", {
        query: { project_id: projectId ?? "" },
      }),
    enabled: Boolean(projectId),
    staleTime: 60_000,
  });

export const issueTypesQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.issueTypes(projectId),
    queryFn: () =>
      api.get<IssueType[]>(ApiPath.issueTypes, { query: { project_id: projectId } }),
    staleTime: 60_000,
  });

/** The resolved field layout for an item's (project, issue-type) — drives the
 * issue view's rail (spec 53 screens). issueTypeId null = the project default. */
export const effectiveScreenQuery = (projectId: string, issueTypeId: string | null) =>
  queryOptions({
    queryKey: queryKeys.effectiveScreen(projectId, issueTypeId),
    queryFn: () =>
      api.get<EffectiveScreen>(ApiPath.screensEffective, {
        query: issueTypeId
          ? { project_id: projectId, issue_type_id: issueTypeId }
          : { project_id: projectId },
      }),
    staleTime: 60_000,
  });

export const projectTeamsQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.projectTeams(projectId),
    queryFn: () => api.get<ProjectTeam[]>(apiProjectTeamsPath(projectId)),
  });

/** Direct project members — requires project.manage (settings/projects handles 403). */
export const projectMembersQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.projectMembers(projectId),
    queryFn: () => api.get<ProjectMember[]>(apiProjectMembersPath(projectId)),
    retry: false,
  });
