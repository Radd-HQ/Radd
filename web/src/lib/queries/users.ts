/** Users + admin, teams, and personal access tokens. */

import type { DirectoryChoice as PeopleChoice } from "@radd/plugin-sdk";
import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiGroupReachPath,
  apiTeamPath,
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

/** Who exists, for naming them (RADD-769): the member-floor directory, NOT `GET /users`, which is
 *  gated on `user.manage` and 403s for ordinary members. The admin table uses `usersAdminQuery`. */
export const usersQuery = queryOptions({
  queryKey: queryKeys.users,
  queryFn: ({ signal }) => api.get<UserSummary[]>(ApiPath.userDirectory, { signal }),
  staleTime: 60_000,
});

export type { PeopleChoice };

/**
 * The same directory, annotated for ONE project (RADD-938): each row gains `has_access`, so a
 * person picker can put entitled people first. Annotation, never filtering — adding a no-access
 * person as a participant is what grants them the project (RADD-937).
 *
 * `includeRequesters` (RADD-1034): EMAIL-source accounts (one per unrecognized sender) are excluded
 * by default, or a forged message would make its sender pickable by everyone. Opt in only where
 * that is meant (the reporter picker on a mail-born ticket); it is part of the query key.
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
    queryFn: ({ signal }) =>
      api.get<UserSummary[]>(ApiPath.userDirectory, {
        signal,
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
    queryFn: ({ signal }) => api.get<UserContentSummary>(apiUserContentPath(userId), { signal }),
    staleTime: 0,
  });

/** RADD-784: is this candidate a viable successor? Access never transfers on
 * delete, so the delete dialog previews the gaps the server would refuse on. */
export const successorCheckQuery = (userId: string, candidateId: string) =>
  queryOptions({
    queryKey: [...queryKeys.users, userId, "successor-check", candidateId] as const,
    queryFn: ({ signal }) => api.get<SuccessorCheck>(apiSuccessorCheckPath(userId, candidateId), { signal }),
    staleTime: 0,
  });

/** The admin Users table (spec 84): server-side q/source/active filters.
 * UNPAGED — the remaining full-set consumers (form defaults, the Jira
 * user mapper) need every account with email; the settings TABLE pages via
 * `usersAdminPageQuery` below. */
export const usersAdminQuery = (filters: { q?: string; source?: string; active?: string }) => {
  const query: Record<string, string> = {};
  if (filters.q) query.q = filters.q;
  if (filters.source) query.source = filters.source;
  if (filters.active) query.active = filters.active;
  return queryOptions({
    queryKey: queryKeys.usersAdmin(query),
    queryFn: ({ signal }) => api.get<User[]>(ApiPath.users, { signal, query }),
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
    queryFn: ({ signal }) => api.getPaged<User>(ApiPath.users, { signal, query }),
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
    meta: entityMeta(Entity.member, Entity.role, Entity.team, Entity.group, Entity.project, Entity.docSpace),
    queryFn: ({ signal }) => api.get<PermissionSource[]>(apiUserPermissionsPath(userId), { signal, query }),
    staleTime: 30_000,
  });
};

/** The spec-92 resource half of the inspector + effective counts (RADD-809). */
export const userAccessQuery = (userId: string) =>
  queryOptions({
    queryKey: [...queryKeys.users, userId, "access"] as const,
    queryFn: ({ signal }) => api.get<UserAccess>(apiUserAccessPath(userId), { signal }),
    staleTime: 30_000,
  });

/** What membership of a team confers (RADD-809). */
export const teamAccessQuery = (teamId: string) =>
  queryOptions({
    queryKey: [...queryKeys.teams, teamId, "access"] as const,
    queryFn: ({ signal }) => api.get<TeamAccess>(apiTeamAccessPath(teamId), { signal }),
    staleTime: 30_000,
  });


/** Duplicate-account candidates (spec 84, instance admin) — merge UI feed. */
export const userDuplicatesQuery = queryOptions({
  queryKey: queryKeys.userDuplicates,
  queryFn: ({ signal }) => api.get<DuplicateUserGroup[]>(ApiPath.usersDuplicates, { signal }),
  retry: false,
});

/** The server-wide team list — every surface (pickers, settings). */
export const teamsQuery = () =>
  queryOptions({
    queryKey: queryKeys.teams,
    queryFn: ({ signal }) => api.get<Team[]>(ApiPath.teams, { signal }),
    staleTime: 60_000,
  });

export const TEAMS_PAGE_SIZE = 50;
export const teamsPageQuery = (q: string, page: number) => queryOptions({
  queryKey: [...queryKeys.teams, "directory", q.trim(), page] as const,
  meta: entityMeta(Entity.team, Entity.role),
  queryFn: ({ signal }) => api.getPaged<Team>(ApiPath.teams, { signal, query: {
    q: q.trim(), limit: String(TEAMS_PAGE_SIZE), offset: String(page * TEAMS_PAGE_SIZE),
  } }),
});
export const teamByIdQuery = (id: string) => queryOptions({
  queryKey: [...queryKeys.teams, "detail", id] as const,
  meta: entityMeta(Entity.team, Entity.role),
  queryFn: ({ signal }) => api.get<Team>(apiTeamPath(id), { signal }),
  enabled: Boolean(id),
});

interface TeamStewardPerson extends PeopleChoice { active: boolean }
interface TeamStewardshipData { owner: TeamStewardPerson | null; managers: TeamStewardPerson[]; total: number }
export const TEAM_STEWARDS_PAGE_SIZE = 50;
export const teamStewardshipQuery = (teamId: string, page: number) => queryOptions({
  queryKey: [...queryKeys.teams, "stewardship", teamId, page] as const,
  meta: entityMeta(Entity.team, Entity.member, Entity.role),
  queryFn: ({ signal }) => api.get<TeamStewardshipData>(`${apiTeamPath(teamId)}/stewardship`, { signal, query: {
    limit: String(TEAM_STEWARDS_PAGE_SIZE), offset: String(page * TEAM_STEWARDS_PAGE_SIZE),
  } }),
});

export const TEAM_MEMBERS_PAGE_SIZE = 50;
export const teamMembersPageQuery = (teamId: string, q: string, page: number) => queryOptions({
  queryKey: [...queryKeys.teamMembers(teamId), "directory", q.trim(), page] as const,
  meta: entityMeta(Entity.team, Entity.member, Entity.role),
  queryFn: ({ signal }) => api.getPaged<TeamMember>(apiTeamMembersPath(teamId), { signal, query: {
    q: q.trim(), limit: String(TEAM_MEMBERS_PAGE_SIZE), offset: String(page * TEAM_MEMBERS_PAGE_SIZE),
  } }),
});
/** The mirrored directory groups (RADD-829) — the team panel's add-group picker. */
export const groupsQuery = () =>
  queryOptions({
    queryKey: ["groups"] as const,
    queryFn: ({ signal }) => api.get<RaddGroup[]>(ApiPath.groups, { signal }),
    staleTime: 60_000,
  });

interface TeamGroupChoice extends TeamGroup { direct_member_count: number; transitive_member_count: number }
export const TEAM_GROUPS_PAGE_SIZE = 50;
const teamGroupWindow = <T extends TeamGroup>(teamId: string, q: string, page: number, candidates: boolean) => queryOptions({
  queryKey: [...queryKeys.teams, teamId, "groups", candidates ? "candidates" : "directory", q.trim(), page] as const,
  meta: entityMeta(Entity.team, Entity.member, Entity.role),
  queryFn: ({ signal }) => api.getPaged<T>(candidates ? `${apiTeamPath(teamId)}/group-candidates` : apiTeamGroupsPath(teamId), {
    signal, query: { q: q.trim(), limit: String(TEAM_GROUPS_PAGE_SIZE), offset: String(page * TEAM_GROUPS_PAGE_SIZE) },
  }),
});
export const teamGroupsPageQuery = (teamId: string, q: string, page: number) => teamGroupWindow<TeamGroup>(teamId, q, page, false);
export const teamGroupCandidatesPageQuery = (teamId: string, q: string, page: number) => teamGroupWindow<TeamGroupChoice>(teamId, q, page, true);
export const teamGroupsPresenceQuery = (teamId: string) => queryOptions({
  queryKey: [...queryKeys.teams, teamId, "groups", "presence"] as const,
  meta: entityMeta(Entity.team, Entity.member, Entity.role),
  queryFn: ({ signal }) => api.getPaged<TeamGroup>(apiTeamGroupsPath(teamId), { signal, query: { limit: "1" } }),
});

/** How many people a grant on a group resolves to, NESTING INCLUDED (RADD-832)
 * — the number the grant UI shows before a grant is saved. */
export const groupReachQuery = (groupId: string) =>
  queryOptions({
    queryKey: ["groups", groupId, "reach"] as const,
    queryFn: ({ signal }) => api.get<GroupReach>(apiGroupReachPath(groupId), { signal }),
    staleTime: 60_000,
  });

/** The caller's personal access tokens. */
export const tokensQuery = queryOptions({
  queryKey: queryKeys.tokens,
  queryFn: ({ signal }) => api.get<ApiToken[]>(ApiPath.tokens, { signal }),
});


