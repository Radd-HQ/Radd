/** Users + admin, directory (LDAP), teams, and personal access tokens. */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiPath,
  apiTeamMembersPath,
  apiUserContentPath,
  apiUserPermissionsPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  ApiToken,
  DirectoryGroup,
  DirectorySyncStatus,
  DirectoryUser,
  DuplicateUserGroup,
  Team,
  TeamMember,
  PermissionSource,
  User,
  UserContentSummary,
  UserSummary,
} from "../types";

/**
 * Who exists, for naming them (RADD-769).
 *
 * Points at the member-floor directory, NOT `GET /users` — that one is gated on
 * `user.manage`, and this query is mounted by the assignee and reporter pickers,
 * the create modal, the bulk bar, `@`-mention autocomplete, the `/` quick
 * actions and page-history bylines. Every one of those fired a 403 for an
 * ordinary member, which is most of the toasts a member ever saw.
 *
 * The admin Users table keeps `usersAdminQuery` below, with the full shape and
 * the spec-84 filters.
 */
export const usersQuery = queryOptions({
  queryKey: queryKeys.users,
  queryFn: () => api.get<UserSummary[]>(ApiPath.userDirectory),
  staleTime: 60_000,
});

/** What a user owns (spec 89) — fetched when the delete dialog opens, never cached
 * long: it decides whether a successor is required. */
export const userContentQuery = (userId: string) =>
  queryOptions({
    queryKey: [...queryKeys.users, userId, "content"] as const,
    queryFn: () => api.get<UserContentSummary>(apiUserContentPath(userId)),
    staleTime: 0,
  });

/** The admin Users table (spec 84): server-side q/source/active filters. */
export const usersAdminQuery = (filters: { q?: string; source?: string; active?: string }) => {
  const query: Record<string, string> = {};
  if (filters.q) query.q = filters.q;
  if (filters.source) query.source = filters.source;
  if (filters.active) query.active = filters.active;
  return queryOptions({
    queryKey: queryKeys.usersAdmin(query),
    queryFn: () => api.get<User[]>(ApiPath.users, { query }),
    placeholderData: keepPreviousData,
  });
};

/** What one person can do, and why (RADD-779). Fetched when their row opens —
 *  it is an admin explaining a specific account, not something to prefetch. */
export const userPermissionsQuery = (userId: string) =>
  queryOptions({
    queryKey: [...queryKeys.users, userId, "permissions"] as const,
    queryFn: () => api.get<PermissionSource[]>(apiUserPermissionsPath(userId)),
    staleTime: 30_000,
  });


/** Duplicate-account candidates (spec 84, instance admin) — merge UI feed. */
export const userDuplicatesQuery = queryOptions({
  queryKey: queryKeys.userDuplicates,
  queryFn: () => api.get<DuplicateUserGroup[]>(ApiPath.usersDuplicates),
  retry: false,
});

/** AD group search (spec 84) — needs an instance admin + a bind account (409). */
export const ldapGroupsQuery = (q: string) =>
  queryOptions({
    queryKey: queryKeys.ldapGroups(q),
    queryFn: () => api.get<DirectoryGroup[]>(ApiPath.ldapGroups, { query: { q } }),
    retry: false,
    placeholderData: keepPreviousData,
  });

/** AD user search for the import picker (spec 84). */
export const ldapDirectoryUsersQuery = (q: string) =>
  queryOptions({
    queryKey: queryKeys.ldapDirectoryUsers(q),
    queryFn: () => api.get<DirectoryUser[]>(ApiPath.ldapDirectoryUsers, { query: { q } }),
    retry: false,
    placeholderData: keepPreviousData,
  });

/** Directory sync status rows (spec 85, instance admin) — the Directory page's
 * last-run lines. */
export const ldapSyncStatusQuery = queryOptions({
  queryKey: queryKeys.ldapSyncStatus,
  queryFn: () => api.get<DirectorySyncStatus>(ApiPath.ldapSyncStatus),
  retry: false,
});

/** The server-wide team list — every surface (pickers, settings, Directory). */
export const teamsQuery = () =>
  queryOptions({
    queryKey: queryKeys.teams,
    queryFn: () => api.get<Team[]>(ApiPath.teams),
    staleTime: 60_000,
  });

export const teamMembersQuery = (teamId: string) =>
  queryOptions({
    queryKey: queryKeys.teamMembers(teamId),
    queryFn: () => api.get<TeamMember[]>(apiTeamMembersPath(teamId)),
  });

/** The caller's personal access tokens. */
export const tokensQuery = queryOptions({
  queryKey: queryKeys.tokens,
  queryFn: () => api.get<ApiToken[]>(ApiPath.tokens),
});
