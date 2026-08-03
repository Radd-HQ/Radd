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
/** Role grants by SUBJECT (a team/user's Roles tab) or by SPACE (RADD-793 —
 *  "who was given access to this space", the question an admin actually asks). */
export const roleGrantsQuery = (subject: {
  teamId?: string;
  userId?: string;
  spaceId?: string;
}) => {
  const key = subject.teamId
    ? `team_id=${subject.teamId}`
    : subject.userId
      ? `user_id=${subject.userId}`
      : `space_id=${subject.spaceId}`;
  return queryOptions({
    queryKey: [
      ...queryKeys.roleGrants,
      subject.teamId ?? subject.userId ?? subject.spaceId ?? "",
    ] as const,
    queryFn: () => api.get<RoleGrant[]>(`${ApiPath.roleGrants}?${key}`),
    enabled: Boolean(subject.teamId || subject.userId || subject.spaceId),
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
