/** Users + admin, directory (LDAP), teams, and personal access tokens. */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import {
  ApiPath,
  apiGroupReachPath,
  apiTeamAccessPath,
  apiTeamGroupsPath,
  apiTeamMembersPath,
  apiUserAccessPath,
  apiSuccessorCheckPath,
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
  GroupReach,
  RaddGroup,
  Team,
  TeamAccess,
  TeamGroup,
  TeamMember,
  PermissionSource,
  User,
  UserAccess,
  SuccessorCheck, UserContentSummary,
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

/**
 * The same directory, annotated for ONE project (RADD-938).
 *
 * For the controls that attach a person TO work — assignee, reporter,
 * participants — where "who exists" is not enough: each row gains `has_access`,
 * so a picker can put entitled people first and mark the rest instead of
 * offering everyone identically and letting you assign an issue to someone who
 * will never see it.
 *
 * Annotation, not filtering. The server marks; the UI groups. Adding a
 * no-access person as a participant is precisely what makes the project visible
 * to them (RADD-937), so the pick has to stay possible.
 *
 * `includeRequesters` (RADD-1034): the directory excludes `UserSource.EMAIL`
 * accounts by default — mailintake provisions one, active, for every
 * unrecognized sender, and without the exclusion a forged message made
 * "Stranger <...@evil.example>" pickable by everyone. Pass `true` only for a
 * surface that genuinely means to offer them (the reporter picker on a
 * mail-born ticket); those rows come back with `external: true`. Folded into
 * the query key so the assignee picker's (filtered) cache and the reporter
 * picker's (opted-in) cache never collide on the same project.
 */
export const projectDirectoryQuery = (
  projectId: string | undefined,
  options?: { includeRequesters?: boolean },
) => {
  const includeRequesters = options?.includeRequesters ?? false;
  return queryOptions({
    queryKey: [
      ...queryKeys.users,
      "project",
      projectId ?? "",
      includeRequesters ? "with-requesters" : "",
    ] as const,
    queryFn: () =>
      api.get<UserSummary[]>(ApiPath.userDirectory, {
        query: {
          project_id: projectId!,
          ...(includeRequesters ? { include_requesters: "true" } : {}),
        },
      }),
    enabled: Boolean(projectId),
    staleTime: 60_000,
  });
};

/** What a user owns (spec 89) — fetched when the delete dialog opens, never cached
 * long: it decides whether a successor is required. */
export const userContentQuery = (userId: string) =>
  queryOptions({
    queryKey: [...queryKeys.users, userId, "content"] as const,
    queryFn: () => api.get<UserContentSummary>(apiUserContentPath(userId)),
    staleTime: 0,
  });

/** RADD-784: is this candidate a viable successor? Access never transfers on
 * delete, so the delete dialog previews the gaps the server would refuse on. */
export const successorCheckQuery = (userId: string, candidateId: string) =>
  queryOptions({
    queryKey: [...queryKeys.users, userId, "successor-check", candidateId] as const,
    queryFn: () => api.get<SuccessorCheck>(apiSuccessorCheckPath(userId, candidateId)),
    staleTime: 0,
  });

/** The admin Users table (spec 84): server-side q/source/active filters.
 * UNPAGED — the full-set consumers (automations vocab, form defaults, the Jira
 * user mapper) need every account with email; the settings TABLE pages via
 * `usersAdminPageQuery` below. */
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

/** Admin Users table page size (RADD-884) — the unfiltered table used to
 * render all 3,088 directory rows at once. */
export const USERS_PAGE_SIZE = 100;

/** The settings Users TABLE: same filters, paged, with the X-Total-Count
 * total (RADD-884). */
export const usersAdminPageQuery = (filters: {
  q?: string;
  source?: string;
  active?: string;
  page: number;
}) => {
  const query: Record<string, string> = {};
  if (filters.q) query.q = filters.q;
  if (filters.source) query.source = filters.source;
  if (filters.active) query.active = filters.active;
  query.limit = String(USERS_PAGE_SIZE);
  query.offset = String((filters.page - 1) * USERS_PAGE_SIZE);
  return queryOptions({
    queryKey: queryKeys.usersAdmin(query),
    queryFn: () => api.getPaged<User>(ApiPath.users, { query }),
    placeholderData: keepPreviousData,
  });
};

/** What one person can do, and why (RADD-779). Fetched when their row opens —
 *  it is an admin explaining a specific account, not something to prefetch.
 *  RADD-809: resolvable at a project or a SPACE scope. */
export const userPermissionsQuery = (
  userId: string,
  scope?: { projectId?: string; spaceId?: string },
) => {
  const query: Record<string, string> = {};
  if (scope?.projectId) query.project_id = scope.projectId;
  if (scope?.spaceId) query.space_id = scope.spaceId;
  return queryOptions({
    queryKey: [...queryKeys.users, userId, "permissions", query] as const,
    queryFn: () => api.get<PermissionSource[]>(apiUserPermissionsPath(userId), { query }),
    staleTime: 30_000,
  });
};

/** The spec-92 resource half of the inspector + effective counts (RADD-809). */
export const userAccessQuery = (userId: string) =>
  queryOptions({
    queryKey: [...queryKeys.users, userId, "access"] as const,
    queryFn: () => api.get<UserAccess>(apiUserAccessPath(userId)),
    staleTime: 30_000,
  });

/** What membership of a team confers (RADD-809). */
export const teamAccessQuery = (teamId: string) =>
  queryOptions({
    queryKey: [...queryKeys.teams, teamId, "access"] as const,
    queryFn: () => api.get<TeamAccess>(apiTeamAccessPath(teamId)),
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

/** The mirrored directory groups (RADD-829) — the team panel's add-group picker. */
export const groupsQuery = () =>
  queryOptions({
    queryKey: ["groups"] as const,
    queryFn: () => api.get<RaddGroup[]>(ApiPath.groups),
    staleTime: 60_000,
  });

/** How many people a grant on a group resolves to, NESTING INCLUDED (RADD-832)
 * — the number the grant UI shows before a grant is saved. */
export const groupReachQuery = (groupId: string) =>
  queryOptions({
    queryKey: ["groups", groupId, "reach"] as const,
    queryFn: () => api.get<GroupReach>(apiGroupReachPath(groupId)),
    staleTime: 60_000,
  });

/** A team's GROUP members (RADD-829). */
export const teamGroupsQuery = (teamId: string) =>
  queryOptions({
    queryKey: [...queryKeys.teams, teamId, "groups"] as const,
    queryFn: () => api.get<TeamGroup[]>(apiTeamGroupsPath(teamId)),
  });

/** The caller's personal access tokens. */
export const tokensQuery = queryOptions({
  queryKey: queryKeys.tokens,
  queryFn: () => api.get<ApiToken[]>(ApiPath.tokens),
});
