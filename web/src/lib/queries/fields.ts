/** Fields registry, labels, access/role grants, and issue link types. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiPath,
} from "../constants";
import { queryKeys } from "./shared";
import { Entity, entityMeta } from "../cache";
import type {
  AccessGrant,
  GrantResourceSpec,
  LinkTypeDef,
} from "../types";
import type { Paged } from "@radd/plugin-sdk";


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

