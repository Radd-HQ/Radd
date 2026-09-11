/** Permissions catalog, roles registry, and instance-wide role grants. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiPath,
  apiRoleGlobalGrantsPath,
} from "../constants";
import { queryKeys } from "./shared";
import { Entity, entityMeta } from "../cache";
import type {
  GlobalGrant,
  PermissionInfo,
  Role,
  RoleGrant,
} from "../types";

/** GET /permissions catalog — static per backend build, cache aggressively. */
export const permissionsCatalogQuery = queryOptions({
  queryKey: queryKeys.permissionsCatalog,
  queryFn: ({ signal }) => api.get<PermissionInfo[]>(ApiPath.permissions, { signal }),
  staleTime: Infinity,
});

/** The global role registry (builtin + custom), readable by any member (spec 06). */
export const rolesQuery = () =>
  queryOptions({
    queryKey: queryKeys.roles,
    meta: entityMeta(Entity.role),
    queryFn: ({ signal }) => api.get<Role[]>(ApiPath.roles, { signal }),
    staleTime: 60_000,
  });

/** Who holds a role instance-wide (spec 87) — the delivery path for global atoms. */
export const roleGlobalGrantsQuery = (roleId: string) =>
  queryOptions({
    queryKey: queryKeys.roleGlobalGrants(roleId),
    queryFn: ({ signal }) => api.get<GlobalGrant[]>(apiRoleGlobalGrantsPath(roleId), { signal }),
    staleTime: 60_000,
  });

export type GrantSubject = { teamId: string } | { userId: string } | { groupId: string };
export interface GrantDirectoryRow extends RoleGrant { role_name: string | null; scope_label: string | null }
export const GRANTS_PAGE_SIZE = 50;
export function grantSubjectParams(subject: GrantSubject) {
  return "teamId" in subject ? { team_id: subject.teamId }
    : "userId" in subject ? { user_id: subject.userId } : { group_id: subject.groupId };
}
export const subjectGrantsPageQuery = (subject: GrantSubject, page: number) => queryOptions({
  queryKey: [...queryKeys.roleGrants, "directory", subject, page] as const,
  meta: entityMeta(Entity.role, Entity.project, Entity.docSpace),
  queryFn: ({ signal }) => api.getPaged<GrantDirectoryRow>(`${ApiPath.roleGrants}/directory`, { signal, query: {
    ...grantSubjectParams(subject), limit: String(GRANTS_PAGE_SIZE), offset: String(page * GRANTS_PAGE_SIZE),
  } }),
});


export interface SpaceGrantDirectoryRow extends RoleGrant {
  role_name: string | null;
  subject_name: string | null;
  subject_active: boolean | null;
  expired: boolean;
}
const scopedGrantsPageQuery = (kind: "space" | "project", id: string, q: string, page: number) => queryOptions({
  queryKey: [...queryKeys.roleGrants, kind === "space" ? "space-directory" : "project-directory", id, q.trim(), page] as const,
  meta: entityMeta(Entity.role, Entity.member, Entity.team, Entity.group, Entity.project, Entity.docSpace),
  queryFn: ({ signal }) => api.getPaged<SpaceGrantDirectoryRow>(`${ApiPath.roleGrants}/by-${kind}/${encodeURIComponent(id)}`, { signal, query: {
    q: q.trim(), limit: String(GRANTS_PAGE_SIZE), offset: String(page * GRANTS_PAGE_SIZE),
  } }),
  enabled: Boolean(id),
});
export const spaceGrantsPageQuery = (spaceId: string, q: string, page: number) => scopedGrantsPageQuery("space", spaceId, q, page);
export const projectGrantsPageQuery = (projectId: string, q: string, page: number) => scopedGrantsPageQuery("project", projectId, q, page);
