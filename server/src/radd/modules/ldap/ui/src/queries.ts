import { keepPreviousData, queryOptions, type QueryClient } from "@tanstack/react-query";
import { api } from "@radd/plugin-sdk";
import {
  LdapPath,
  ldapKeys,
  type DeployStatus,
  type DirectoryGroup,
  type DirectorySyncStatus,
  type DirectoryUser,
  type MirroredGroup,
} from "./types";

/** Deploy status (the projects module's endpoint): sign-in, bind account, workers. */
export const deployStatusQuery = queryOptions({
  queryKey: ["instance-status"] as const,
  queryFn: ({ signal }) => api.get<DeployStatus>(LdapPath.instanceStatus, { signal }),
  staleTime: 60_000,
  retry: false,
});

/** Both sync-state rows (null = never ran). Readable without a bind account. */
export const syncStatusQuery = queryOptions({
  queryKey: ldapKeys.syncStatus,
  queryFn: ({ signal }) => api.get<DirectorySyncStatus>(LdapPath.syncStatus, { signal }),
  retry: false,
});

/** AD group search under the group base — needs a bind account (409 without one). */
export const directoryGroupsQuery = (q: string) =>
  queryOptions({
    queryKey: ldapKeys.groups(q),
    queryFn: ({ signal }) => api.get<DirectoryGroup[]>(LdapPath.groups, { signal, query: { q } }),
    retry: false,
    placeholderData: keepPreviousData,
  });

/** AD user search for the import picker (cn / sAMAccountName / mail). */
export const directoryUsersQuery = (q: string) =>
  queryOptions({
    queryKey: ldapKeys.directoryUsers(q),
    queryFn: ({ signal }) => api.get<DirectoryUser[]>(LdapPath.directoryUsers, { signal, query: { q } }),
    retry: false,
    placeholderData: keepPreviousData,
  });

/** What Radd has mirrored (the groups module's list) — shares the host's `groups` cache entry. */
export const mirroredGroupsQuery = queryOptions({
  queryKey: ["groups"] as const,
  queryFn: ({ signal }) => api.get<MirroredGroup[]>(LdapPath.mirroredGroups, { signal }),
  staleTime: 60_000,
});

/** Refresh the host lists a directory write changed, by their cache-key prefixes. */
export function refreshAfterImport(queryClient: QueryClient, ...keys: readonly (readonly string[])[]) {
  return Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
}
