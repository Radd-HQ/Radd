/** Transport for the Jira importer (specs 90, 100): paths, query keys, queries.
 * Everything here is this plugin's own — including the keys under which it reads
 * the states, types, teams and people its plan editor maps onto. */
import { api, ApiError } from "@radd/plugin-sdk";
import type { JiraPlan } from "./plan-types";
import type {
  JiraConnection,
  JiraConnectionStatus,
  JiraProject,
  JiraRun,
  JiraSnapshot,
  PendingSummary,
  TargetIssueType,
  TargetProject,
  TargetState,
  TargetTeam,
  TargetUser,
} from "./types";
import { TERMINAL_JIRA_RUN_STAGES, TERMINAL_SNAPSHOT_STAGES } from "./types";

export const JiraPath = {
  // Spec 100: connections are admin-managed rows, not environment variables.
  connections: "/jira/connections",
  status: "/jira/status",
  projects: "/jira/projects",
  // RADD-1101: the JQL sanity check — a bad query answers 422 with Jira's reason.
  preview: "/jira/preview",
  // A JQL result set is downloaded ONCE into a cached snapshot, and every later
  // step reads that instead of hammering Jira again.
  snapshots: "/jira/snapshots",
  plans: "/jira/plans",
  runs: "/jira/runs",
  // Cross-project references still waiting for their target.
  pending: "/jira/pending",
  relink: "/jira/relink",
} as const;

/** The owners' public reads the plan editor maps onto. */
const TargetPath = {
  projectByKey: (key: string) => `/projects/by-key/${encodeURIComponent(key.toUpperCase())}`,
  states: "/states",
  issueTypes: "/issue-types",
  teams: "/teams",
  users: "/users",
} as const;

const ROOT = "jiraimport";
export const jiraKeys = {
  connections: [ROOT, "connections"] as const,
  status: [ROOT, "status"] as const,
  projectsAll: [ROOT, "projects"] as const,
  projects: (connectionId: string | null) => [ROOT, "projects", { connectionId }] as const,
  snapshots: [ROOT, "snapshots"] as const,
  plans: [ROOT, "plans"] as const,
  plan: (planId: string) => [ROOT, "plan", { planId }] as const,
  runs: [ROOT, "runs"] as const,
  pending: [ROOT, "pending"] as const,
  project: (key: string) => [ROOT, "target", "project", key.toUpperCase()] as const,
  states: (projectId: string) => [ROOT, "target", "states", projectId] as const,
  issueTypes: (projectId: string) => [ROOT, "target", "issue-types", projectId] as const,
  teams: [ROOT, "target", "teams"] as const,
  users: [ROOT, "target", "users"] as const,
};

const Q = (signal: AbortSignal) => ({ signal });

/** Every configured Jira instance. Credentials are never in the response. */
export const connectionsQuery = () => ({
  queryKey: jiraKeys.connections,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<JiraConnection[]>(JiraPath.connections, Q(signal)),
  staleTime: 30_000,
});

/**
 * Is the DEFAULT connection live? Never rejects for an unreachable Jira — an
 * unusable connection comes back as `ok: false` with a reason, which is a state
 * to render rather than an error boundary.
 */
export const statusQuery = () => ({
  queryKey: jiraKeys.status,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<JiraConnectionStatus>(JiraPath.status, Q(signal)),
  retry: false,
});

/** Projects the connection's service account can see — the picker's source. */
export const jiraProjectsQuery = (connectionId: string | null) => ({
  queryKey: jiraKeys.projects(connectionId),
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<JiraProject[]>(JiraPath.projects, {
    signal, query: { connection_id: connectionId ?? undefined },
  }),
  enabled: Boolean(connectionId),
  staleTime: 60_000,
});

/**
 * Cached downloads, newest first. Polling is self-regulating: the interval is a
 * function of the data, so the list refetches while a download is moving and
 * goes quiet the moment every one of them has settled.
 */
export const snapshotsQuery = (pollMs = 1500) => ({
  queryKey: jiraKeys.snapshots,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<JiraSnapshot[]>(JiraPath.snapshots, Q(signal)),
  refetchInterval: (query: { state: { data?: JiraSnapshot[] } }) =>
    (query.state.data ?? []).every((s) => TERMINAL_SNAPSHOT_STAGES.includes(s.stage)) ? false : pollMs,
});

/** Import plans — one per snapshot, holding every mapping decision. */
export const plansQuery = () => ({
  queryKey: jiraKeys.plans,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<JiraPlan[]>(JiraPath.plans, Q(signal)),
});

export const planQuery = (planId: string) => ({
  queryKey: jiraKeys.plan(planId),
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<JiraPlan>(`${JiraPath.plans}/${planId}`, Q(signal)),
  enabled: Boolean(planId),
});

/** Dry runs, imports and rollbacks. Polls only while one is moving. */
export const runsQuery = (pollMs = 1500) => ({
  queryKey: jiraKeys.runs,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<JiraRun[]>(JiraPath.runs, Q(signal)),
  refetchInterval: (query: { state: { data?: JiraRun[] } }) =>
    (query.state.data ?? []).every((r) => TERMINAL_JIRA_RUN_STAGES.includes(r.stage)) ? false : pollMs,
});

/** How many cross-project references are still waiting for their target. */
export const pendingQuery = () => ({
  queryKey: jiraKeys.pending,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<PendingSummary>(JiraPath.pending, Q(signal)),
  staleTime: 30_000,
});

/** A plan names its target project by KEY until provisioning creates it; null = not created yet. */
export const targetProjectQuery = (key: string) => ({
  queryKey: jiraKeys.project(key),
  queryFn: async ({ signal }: { signal: AbortSignal }): Promise<TargetProject | null> => {
    try {
      return await api.get<TargetProject>(TargetPath.projectByKey(key), Q(signal));
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  },
  retry: false,
});

/** The target project's workflow states — a status maps onto one BY NAME, taking its category. */
export const targetStatesQuery = (projectId: string) => ({
  queryKey: jiraKeys.states(projectId),
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    api.get<TargetState[]>(TargetPath.states, { signal, query: { project_id: projectId } }),
  enabled: Boolean(projectId),
  staleTime: 60_000,
});

/** The target project's issue types — an issue type maps onto one BY NAME. */
export const targetIssueTypesQuery = (projectId: string) => ({
  queryKey: jiraKeys.issueTypes(projectId),
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    api.get<TargetIssueType[]>(TargetPath.issueTypes, { signal, query: { project_id: projectId } }),
  enabled: Boolean(projectId),
  staleTime: 60_000,
});

/** Every team — a Jira team value translates onto a team NAME. */
export const targetTeamsQuery = () => ({
  queryKey: jiraKeys.teams,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<TargetTeam[]>(TargetPath.teams, Q(signal)),
  staleTime: 60_000,
});

/** The ADMIN directory (RADD-769): mapping Jira accounts onto local ones is
 * matching by ADDRESS, and the whole importer is instance-admin only. */
export const targetUsersQuery = () => ({
  queryKey: jiraKeys.users,
  queryFn: ({ signal }: { signal: AbortSignal }) => api.get<TargetUser[]>(TargetPath.users, Q(signal)),
  staleTime: 60_000,
});
