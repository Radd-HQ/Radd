/** Integrations. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiServiceAccountKeysPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  ServiceAccount,
  ServiceAccountKey,
} from "../types";

export const SERVICE_ACCOUNT_PAGE_SIZE = 50;
interface ServiceKeySummary extends Omit<ServiceAccountKey, "scopes"> {
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
