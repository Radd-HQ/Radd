/** Projects, states/transitions, screens, issue types, field writability, and membership. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta, projectEntityMeta, itemEntityMeta } from "@radd/plugin-sdk";
import {
  ApiPath,
  apiItemAllowedTransitionsPath,
  apiProjectContentPath,
  apiProjectThreadResolutionPath,
  apiProjectTransitionsPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  AllowedTransitions,
  EffectiveScreen,
  IssueType,
  ProjectContentSummary,
  State,
  StateCategoryRow,
  ThreadResolutionPolicy,
  Transition,
} from "../types";


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
    meta: itemEntityMeta(itemId, Entity.transition, Entity.item, Entity.comment, Entity.role, Entity.team,
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

/** RADD-1283: the project's thread-resolution rules (project.manage). */
export const threadResolutionQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.threadResolution(projectId),
    queryFn: ({ signal }) =>
      api.get<ThreadResolutionPolicy>(apiProjectThreadResolutionPath(projectId), { signal }),
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
