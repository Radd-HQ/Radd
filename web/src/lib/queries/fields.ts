/** Fields registry, labels, access/role grants, and issue link types. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  AccessGrant,
  FieldDef,
  Label,
  LinkTypeDef,
  RoleGrant,
} from "../types";

export const fieldsQuery = () =>
  queryOptions({
    queryKey: queryKeys.fields,
    queryFn: () => api.get<FieldDef[]>(ApiPath.fields),
    staleTime: 60_000,
  });

/** Access grants (spec 92) on a resource — the reusable GrantsEditor reads this. */
export const grantsQuery = (resourceType: string, resourceId: string) =>
  queryOptions({
    queryKey: [...queryKeys.grants, resourceType, resourceId] as const,
    queryFn: () =>
      api.get<AccessGrant[]>(
        `${ApiPath.grants}?resource_type=${resourceType}&resource_id=${resourceId}`,
      ),
    staleTime: 30_000,
  });

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
    queryFn: () =>
      api.get<RoleGrant[]>(`${ApiPath.roleGrants}?${GRANT_QUERY_PARAM[named!]}=${id!}`),
    enabled: Boolean(id),
    staleTime: 30_000,
  });
};

/** Issue link types (spec 91). No projectId = every type (admin); a projectId =
 * the manual types offered on an item in that project (global + project-scoped). */
export const linkTypesQuery = (projectId?: string) =>
  queryOptions({
    queryKey: [...queryKeys.linkTypes, projectId ?? "all"] as const,
    queryFn: () =>
      api.get<LinkTypeDef[]>(
        projectId ? `${ApiPath.linkTypes}?project_id=${projectId}` : ApiPath.linkTypes,
      ),
    staleTime: 60_000,
  });

export const labelsQuery = () =>
  queryOptions({
    queryKey: queryKeys.labels,
    queryFn: () => api.get<Label[]>(ApiPath.labels),
    staleTime: 60_000,
  });
