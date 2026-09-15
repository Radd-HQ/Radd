/** Fields registry, labels, access/role grants, and issue link types. */

import { queryOptions } from "@tanstack/react-query";
import { api, type Paged } from "../api";
import {
  ApiPath,
} from "../constants";
import { queryKeys } from "./shared";
import { Entity, entityMeta } from "../cache";
import type {
  AccessGrant,
  FieldDef,
  GrantResourceSpec,
  Label,
  LinkTypeDef,
  RoleGrant,
} from "../types";

/**
 * The field registry — or, given a project, only the fields IN SCOPE for it
 * (global ones plus those scoped to it; RADD-1158). A surface that WRITES
 * values for a project asks for the scoped set, so a field scoped elsewhere
 * can never be offered and then refused. The server narrows through the same
 * predicate it validates with; a client-side filter over the full registry
 * would be a second copy of that rule.
 */
export const fieldsQuery = (projectId?: string) =>
  queryOptions({
    queryKey: projectId ? queryKeys.projectFields(projectId) : queryKeys.fields,
    meta: entityMeta(Entity.field),
    queryFn: ({ signal }) =>
      api.get<FieldDef[]>(ApiPath.fields, { signal, query: { project_id: projectId } }),
    staleTime: 60_000,
  });

/**
 * Every registered resource's GRANT MODEL (RADD-947) — accesses, subject kinds,
 * whether grants can be project-scoped. Instance-wide and effectively static
 * (it changes only when a plugin mounts), so it caches for the session and
 * every open editor shares one fetch.
 */
export const grantResourcesQuery = () =>
  queryOptions({
    queryKey: [...queryKeys.grants, "resources"] as const,
    queryFn: ({ signal }) => api.get<GrantResourceSpec[]>(`${ApiPath.grants}/resources`, { signal }),
    staleTime: 5 * 60_000,
  });

export interface AccessGrantDirectoryRow extends AccessGrant {
  subject_name: string | null; project_key: string | null; expired: boolean;
}
export const RESOURCE_GRANTS_PAGE_SIZE = 50;
/** Management includes expired rows; authorization reads continue to exclude them. */
export const resourceGrantsPageQuery = (resourceType: string, resourceId: string, q: string, page: number, projectId?: string | null) => {
  const prefix = [...queryKeys.grants, resourceType, resourceId, "directory", q, projectId === undefined ? "all" : projectId === null ? "global" : projectId] as const;
  return queryOptions({
    queryKey: [...prefix, page] as const,
    // Retain the current window during paging, never across resources or searches.
    placeholderData: (previous: Paged<AccessGrantDirectoryRow> | undefined, query) => JSON.stringify(query?.queryKey.slice(0, -1)) === JSON.stringify(prefix) ? previous : undefined,
    meta: entityMeta(Entity.accessGrant, Entity.role, Entity.member, Entity.team, Entity.group, Entity.project, Entity.docSpace, Entity.page,
      ...(resourceType === "view" ? [Entity.view] : resourceType === "dashboard" ? [Entity.dashboard] : [])),
    queryFn: ({ signal }) => api.getPaged<AccessGrantDirectoryRow>(`${ApiPath.grants}/directory`, {
      query: { resource_type: resourceType, resource_id: resourceId, project_id: projectId ?? undefined, global_only: projectId === null ? "true" : undefined, q, limit: String(RESOURCE_GRANTS_PAGE_SIZE), offset: String(page * RESOURCE_GRANTS_PAGE_SIZE) }, signal,
    }),
  });
};

/** Role grants (spec 91) held by one subject — the team/user Roles section. */
/**
 * Role grants by SUBJECT (a team/user/group's Roles tab) or by SCOPE — a space
 * (RADD-793) or a project (RADD-929). The scope directions are the question an
 * admin actually asks: "who was given access to this?"
 *
 * The parameter name is the server's, so adding a direction is one entry here.
 * The previous shape spelled the same choice out three times — a ternary chain,
 * a query key and an `enabled` guard — and the guard had dropped `groupId`,
 * which meant every group's grants query was permanently disabled and the
 * `groupId` subject the API supports was unreachable no matter who called it.
 */
const GRANT_QUERY_PARAM = {
  teamId: "team_id",
  userId: "user_id",
  groupId: "group_id",
  spaceId: "space_id",
  projectId: "project_id",
} as const;

export const roleGrantsQuery = (subject: Partial<Record<keyof typeof GRANT_QUERY_PARAM, string>>) => {
  const named = (Object.keys(GRANT_QUERY_PARAM) as (keyof typeof GRANT_QUERY_PARAM)[]).find(
    (field) => subject[field],
  );
  const id = named ? subject[named] : undefined;
  return queryOptions({
    queryKey: [...queryKeys.roleGrants, named ?? "", id ?? ""] as const,
    meta: entityMeta(Entity.role),
    queryFn: ({ signal }) =>
      api.get<RoleGrant[]>(`${ApiPath.roleGrants}?${GRANT_QUERY_PARAM[named!]}=${id!}`, { signal }),
    enabled: Boolean(id),
    staleTime: 30_000,
  });
};

/** Issue link types (spec 91). No projectId = every type (admin); a projectId =
 * the manual types offered on an item in that project (global + project-scoped). */
export const linkTypesQuery = (projectId?: string) =>
  queryOptions({
    queryKey: [...queryKeys.linkTypes, projectId ?? "all"] as const,
    queryFn: ({ signal }) =>
      api.get<LinkTypeDef[]>(
        projectId ? `${ApiPath.linkTypes}?project_id=${projectId}` : ApiPath.linkTypes, { signal },
      ),
    staleTime: 60_000,
  });

export const labelsQuery = () =>
  queryOptions({
    queryKey: queryKeys.labels,
    queryFn: ({ signal }) => api.get<Label[]>(ApiPath.labels, { signal }),
    staleTime: 60_000,
  });
