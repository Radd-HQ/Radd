/** Integrations. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import { ApiPath, apiServiceAccountKeysPath } from "../constants";
import { queryKeys } from "./shared";
import type {
  ForgejoConnection,
  ForgejoRepo,
  ServiceAccount,
  ServiceAccountKey,
} from "../types";

/** Spec 111: Forgejo hosts and their repositories (admin). */
export const forgejoConnectionsQuery = () =>
  queryOptions({
    queryKey: queryKeys.forgejoConnections,
    queryFn: ({ signal }) => api.get<ForgejoConnection[]>(ApiPath.forgejoConnections, { signal }),
    meta: entityMeta(Entity.forgejoConnection),
  });

export const forgejoReposQuery = () =>
  queryOptions({
    queryKey: queryKeys.forgejoRepos,
    queryFn: ({ signal }) => api.get<ForgejoRepo[]>(ApiPath.forgejoRepos, { signal }),
    meta: entityMeta(Entity.forgejoRepo),
  });

/** Spec 113: service accounts and the keys they hold (admin). */
export const serviceAccountsQuery = () =>
  queryOptions({
    queryKey: queryKeys.serviceAccounts,
    queryFn: ({ signal }) => api.get<ServiceAccount[]>(ApiPath.serviceAccounts, { signal }),
    meta: entityMeta(Entity.serviceAccount),
  });

export const serviceAccountKeysQuery = (accountId: string) =>
  queryOptions({
    queryKey: queryKeys.serviceAccountKeys(accountId),
    queryFn: ({ signal }) => api.get<ServiceAccountKey[]>(apiServiceAccountKeysPath(accountId), { signal }),
    meta: entityMeta(Entity.serviceAccount),
  });

export const SERVICE_ACCOUNT_PAGE_SIZE = 50;
export interface ServiceKeySummary extends Omit<ServiceAccountKey, "scopes"> {
  restricted: boolean; global_count: number; project_count: number;
}
const accountMeta = entityMeta(Entity.serviceAccount, Entity.role, Entity.member, Entity.team, Entity.group);
export const serviceAccountDirectoryQuery = (q: string, page: number) => queryOptions({
  queryKey: [...queryKeys.serviceAccounts, "directory", q, page] as const, meta: accountMeta,
  queryFn: ({ signal }) => api.getPaged<ServiceAccount>(ApiPath.serviceAccounts, {
    signal, query: { q, limit: String(SERVICE_ACCOUNT_PAGE_SIZE), offset: String(page * SERVICE_ACCOUNT_PAGE_SIZE) },
  }),
});
export const serviceAccountQuery = (id: string) => queryOptions({
  queryKey: [...queryKeys.serviceAccounts, "detail", id] as const, meta: accountMeta,
  queryFn: ({ signal }) => api.get<ServiceAccount>(`${ApiPath.serviceAccounts}/${id}`, { signal }),
});
export const serviceKeyDirectoryQuery = (id: string, q: string, page: number) => queryOptions({
  queryKey: [...queryKeys.serviceAccountKeys(id), "directory", q, page] as const, meta: accountMeta,
  queryFn: ({ signal }) => api.getPaged<ServiceKeySummary>(`${apiServiceAccountKeysPath(id)}/directory`, {
    signal, query: { q, limit: String(SERVICE_ACCOUNT_PAGE_SIZE), offset: String(page * SERVICE_ACCOUNT_PAGE_SIZE) },
  }),
});
