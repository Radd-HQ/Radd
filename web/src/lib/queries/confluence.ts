/**
 * Confluence importer queries (spec 117).
 *
 * Progress is POLLED, not pushed: a download and a run are in-process tasks whose
 * row is the progress bar. `refetchInterval` is a function of the data, so it
 * stops the moment everything is terminal rather than polling an idle page
 * forever.
 */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { ApiPath } from "../constants";
import { queryKeys } from "./shared";
import type {
  ConfluenceConnection,
  ConfluencePageNode,
  ConfluencePlan,
  ConfluenceRun,
  ConfluenceSnapshot,
  ConfluenceSpace,
  ConfluenceStatus,
} from "../types";
import { CONFLUENCE_TERMINAL_STAGES } from "../types";

const POLL_MS = 1500;

/** Keep polling only while something is still moving. */
const pollWhileRunning = <T extends { stage: string }>(rows: T[] | undefined) =>
  rows?.some((row) => !CONFLUENCE_TERMINAL_STAGES.has(row.stage)) ? POLL_MS : false;

export const confluenceConnectionsQuery = () =>
  queryOptions({
    queryKey: queryKeys.confluenceConnections,
    queryFn: ({ signal }) => api.get<ConfluenceConnection[]>(ApiPath.confluenceConnections, { signal }),
    staleTime: 30_000,
  });

/**
 * Is the default connection live? Never rejects for an unreachable Confluence —
 * `ok: false` with a reason is a state to render, not an error boundary, and
 * `configured: false` is the answer before anything is set up at all.
 */
export const confluenceStatusQuery = (enabled = true) =>
  queryOptions({
    queryKey: queryKeys.confluenceStatus,
    queryFn: ({ signal }) => api.get<ConfluenceStatus>(ApiPath.confluenceStatus, { signal }),
    enabled,
    retry: false,
  });

export const confluenceSpacesQuery = (connectionId: string | null, enabled = true) =>
  queryOptions({
    queryKey: queryKeys.confluenceSpaces(connectionId),
    queryFn: ({ signal }) =>
      api.get<ConfluenceSpace[]>(ApiPath.confluenceSpaces, {
        signal,
        query: { connection_id: connectionId || undefined },
      }),
    enabled,
    retry: false,
    staleTime: 60_000,
  });

/**
 * ONE level of the remote tree: a space's roots, or one page's children.
 *
 * Lazy on purpose. Fetching a real 6000-page space up front took 61 requests and
 * over two minutes — the picker showed nothing at all for the whole time, which
 * read as "there are no pages" rather than "still loading".
 */
export const confluenceTreeQuery = (
  spaceKey: string,
  parentId = "",
  enabled = true,
) =>
  queryOptions({
    queryKey: queryKeys.confluenceTree(spaceKey, parentId),
    queryFn: ({ signal }) =>
      api.get<ConfluencePageNode[]>(`${ApiPath.confluenceSpaces}/${spaceKey}/tree`, {
        signal,
        query: { parent_id: parentId || undefined },
      }),
    enabled: enabled && Boolean(spaceKey),
    retry: false,
    staleTime: 60_000,
  });

export const confluenceSnapshotsQuery = () =>
  queryOptions({
    queryKey: queryKeys.confluenceSnapshots,
    queryFn: ({ signal }) => api.get<ConfluenceSnapshot[]>(ApiPath.confluenceSnapshots, { signal }),
    refetchInterval: (query) => pollWhileRunning(query.state.data),
  });

export const confluencePlansQuery = () =>
  queryOptions({
    queryKey: queryKeys.confluencePlans,
    queryFn: ({ signal }) => api.get<ConfluencePlan[]>(ApiPath.confluencePlans, { signal }),
  });

export const confluencePlanQuery = (planId: string) =>
  queryOptions({
    queryKey: queryKeys.confluencePlan(planId),
    queryFn: ({ signal }) => api.get<ConfluencePlan>(`${ApiPath.confluencePlans}/${planId}`, { signal }),
    enabled: Boolean(planId),
  });

export const confluenceRunsQuery = () =>
  queryOptions({
    queryKey: queryKeys.confluenceRuns,
    queryFn: ({ signal }) => api.get<ConfluenceRun[]>(ApiPath.confluenceRuns, { signal }),
    refetchInterval: (query) => pollWhileRunning(query.state.data),
  });
