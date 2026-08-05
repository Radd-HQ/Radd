/** Jira import: connections, connection status, projects, and runs (specs 90, 100). */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { ApiPath } from "../constants";
import { queryKeys } from "./shared";
import type {
  JiraConnection,
  JiraConnectionStatus,
  JiraPlan,
  JiraProject,
  JiraRun,
  JiraSnapshot,
  PendingSummary,
} from "../types";

/** Every configured Jira instance. Credentials are never in the response. */
export const jiraConnectionsQuery = () =>
  queryOptions({
    queryKey: queryKeys.jiraConnections,
    queryFn: () => api.get<JiraConnection[]>(ApiPath.jiraConnections),
    staleTime: 30_000,
  });

/**
 * Is the DEFAULT connection live? Never rejects for an unreachable Jira — an
 * unusable connection comes back as `ok: false` with a reason, which is a state
 * to render rather than an error boundary.
 */
export const jiraStatusQuery = (enabled = true) =>
  queryOptions({
    queryKey: queryKeys.jiraStatus,
    queryFn: () => api.get<JiraConnectionStatus>(ApiPath.jiraStatus),
    enabled,
    retry: false,
  });

/** Projects the connection's service account can see — the picker's source. */
export const jiraProjectsQuery = (connectionId: string | null, enabled = true) =>
  queryOptions({
    queryKey: queryKeys.jiraProjects(connectionId),
    queryFn: () =>
      api.get<JiraProject[]>(
        connectionId
          ? `${ApiPath.jiraProjects}?connection_id=${connectionId}`
          : ApiPath.jiraProjects,
      ),
    enabled,
    staleTime: 60_000,
  });

/** A download is over, whatever the outcome. */
const snapshotSettled = (snapshot: JiraSnapshot) =>
  snapshot.stage === "done" || snapshot.stage === "failed" || snapshot.stage === "canceled";

/**
 * Cached downloads, newest first.
 *
 * Polling is self-regulating: the interval is a function of the data, so the
 * list refetches while a download is moving and goes quiet the moment every one
 * of them has settled — rather than polling forever, or making each caller
 * thread an `isRunning` flag back in.
 */
export const jiraSnapshotsQuery = (pollMs = 1500) =>
  queryOptions({
    queryKey: queryKeys.jiraSnapshots,
    queryFn: () => api.get<JiraSnapshot[]>(ApiPath.jiraSnapshots),
    refetchInterval: (query) =>
      (query.state.data ?? []).every(snapshotSettled) ? false : pollMs,
  });

/** Import plans — one per snapshot, holding every mapping decision. */
export const jiraPlansQuery = () =>
  queryOptions({
    queryKey: queryKeys.jiraPlans,
    queryFn: () => api.get<JiraPlan[]>(ApiPath.jiraPlans),
  });

export const jiraPlanQuery = (planId: string) =>
  queryOptions({
    queryKey: queryKeys.jiraPlan(planId),
    queryFn: () => api.get<JiraPlan>(`${ApiPath.jiraPlans}/${planId}`),
    enabled: Boolean(planId),
  });

const runSettled = (run: JiraRun) =>
  run.stage === "done" || run.stage === "failed" || run.stage === "canceled";

/** Dry runs, imports and rollbacks. Polls only while one is moving. */
export const jiraRunsQuery = (pollMs = 1500) =>
  queryOptions({
    queryKey: queryKeys.jiraRuns,
    queryFn: () => api.get<JiraRun[]>(ApiPath.jiraRuns),
    refetchInterval: (query) => ((query.state.data ?? []).every(runSettled) ? false : pollMs),
  });

/** How many cross-project references are still waiting for their target. */
export const jiraPendingQuery = () =>
  queryOptions({
    queryKey: queryKeys.jiraPending,
    queryFn: () => api.get<PendingSummary>(ApiPath.jiraPending),
    staleTime: 30_000,
  });
