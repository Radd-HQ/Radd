/** Permissions catalog, roles registry, and instance-wide role grants. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiPath,
  apiRoleGlobalGrantsPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  GlobalGrant,
  PermissionInfo,
  Role,
} from "../types";

/** GET /permissions catalog — static per backend build, cache aggressively. */
export const permissionsCatalogQuery = queryOptions({
  queryKey: queryKeys.permissionsCatalog,
  queryFn: () => api.get<PermissionInfo[]>(ApiPath.permissions),
  staleTime: Infinity,
});

/** The global role registry (builtin + custom), readable by any member (spec 06). */
export const rolesQuery = () =>
  queryOptions({
    queryKey: queryKeys.roles,
    queryFn: () => api.get<Role[]>(ApiPath.roles),
    staleTime: 60_000,
  });

/** Who holds a role instance-wide (spec 87) — the delivery path for global atoms. */
export const roleGlobalGrantsQuery = (roleId: string) =>
  queryOptions({
    queryKey: queryKeys.roleGlobalGrants(roleId),
    queryFn: () => api.get<GlobalGrant[]>(apiRoleGlobalGrantsPath(roleId)),
    staleTime: 60_000,
  });
