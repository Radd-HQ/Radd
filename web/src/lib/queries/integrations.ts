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
    queryFn: () => api.get<ForgejoConnection[]>(ApiPath.forgejoConnections),
    meta: entityMeta(Entity.forgejoConnection),
  });

export const forgejoReposQuery = () =>
  queryOptions({
    queryKey: queryKeys.forgejoRepos,
    queryFn: () => api.get<ForgejoRepo[]>(ApiPath.forgejoRepos),
    meta: entityMeta(Entity.forgejoRepo),
  });

/** Spec 113: service accounts and the keys they hold (admin). */
export const serviceAccountsQuery = () =>
  queryOptions({
    queryKey: queryKeys.serviceAccounts,
    queryFn: () => api.get<ServiceAccount[]>(ApiPath.serviceAccounts),
    meta: entityMeta(Entity.serviceAccount),
  });

export const serviceAccountKeysQuery = (accountId: string) =>
  queryOptions({
    queryKey: queryKeys.serviceAccountKeys(accountId),
    queryFn: () => api.get<ServiceAccountKey[]>(apiServiceAccountKeysPath(accountId)),
    meta: entityMeta(Entity.serviceAccount),
  });
