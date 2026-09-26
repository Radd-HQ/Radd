/** The Confluence importer's reads. Progress is polled, and `refetchInterval` is a function of the
 * data, so polling stops once every row is terminal. Keys start with the plugin's name, so disabling
 * the plugin drops its cache. */
import { queryOptions } from "@tanstack/react-query";
import { api } from "@radd/plugin-sdk";
import {
  CONFLUENCE_TERMINAL_STAGES,
  type ConfluenceConnection,
  type ConfluencePageNode,
  type ConfluencePlan,
  type ConfluenceRun,
  type ConfluenceSnapshot,
  type ConfluenceSpace,
  type ConfluenceStatus,
  type PageRendererChoice,
} from "./types";

export const ConfluencePath = {
  connections: "/confluence/connections",
  status: "/confluence/status",
  spaces: "/confluence/spaces",
  snapshots: "/confluence/snapshots",
  plans: "/confluence/plans",
  runs: "/confluence/runs",
} as const;

/** Destinations owned by other plugins, read through their public API or option directories. */
const PAGE_RENDERERS_PATH = "/pages/extensions";
export const OptionResource = { space: "page-spaces", group: "groups" } as const;

const PLUGIN = "confluenceimport";
export const confluenceKeys = {
  connections: [PLUGIN, "connections"] as const,
  status: [PLUGIN, "status"] as const,
  spaces: (connectionId: string | null) => [PLUGIN, "spaces", { connectionId }] as const,
  tree: (spaceKey: string, parentId: string, connectionId: string | null) =>
    [PLUGIN, "tree", { spaceKey, parentId, connectionId }] as const,
  snapshots: [PLUGIN, "snapshots"] as const,
  plans: [PLUGIN, "plans"] as const,
  plan: (planId: string) => [PLUGIN, "plan", { planId }] as const,
  runs: [PLUGIN, "runs"] as const,
  renderers: [PLUGIN, "page-renderers"] as const,
};

const POLL_MS = 1500;

/** Keep polling only while something is still moving. */
const pollWhileRunning = <T extends { stage: string }>(rows: T[] | undefined) =>
  rows?.some((row) => !CONFLUENCE_TERMINAL_STAGES.has(row.stage)) ? POLL_MS : false;

export const connectionsQuery = () =>
  queryOptions({
    queryKey: confluenceKeys.connections,
    queryFn: ({ signal }) => api.get<ConfluenceConnection[]>(ConfluencePath.connections, { signal }),
    staleTime: 30_000,
  });

/** Is the default connection live? `ok: false` with a reason is a state to render, not an error;
 * `configured: false` means nothing is set up yet. */
export const statusQuery = () =>
  queryOptions({
    queryKey: confluenceKeys.status,
    queryFn: ({ signal }) => api.get<ConfluenceStatus>(ConfluencePath.status, { signal }),
    retry: false,
  });

export const spacesQuery = (connectionId: string | null) =>
  queryOptions({
    queryKey: confluenceKeys.spaces(connectionId),
    queryFn: ({ signal }) =>
      api.get<ConfluenceSpace[]>(ConfluencePath.spaces, {
        signal,
        query: { connection_id: connectionId || undefined },
      }),
    retry: false,
    staleTime: 60_000,
  });

/** ONE level of the remote tree (a space's roots, or one page's children) — lazy: a 6000-page space
 * fetched whole took 61 requests and 2+ minutes, rendering nothing. */
export const treeQuery = (spaceKey: string, parentId: string, connectionId: string | null) =>
  queryOptions({
    queryKey: confluenceKeys.tree(spaceKey, parentId, connectionId),
    queryFn: ({ signal }) =>
      api.get<ConfluencePageNode[]>(`${ConfluencePath.spaces}/${spaceKey}/tree`, {
        signal,
        query: { parent_id: parentId || undefined, connection_id: connectionId || undefined },
      }),
    enabled: Boolean(spaceKey),
    retry: false,
    staleTime: 60_000,
  });

export const snapshotsQuery = () =>
  queryOptions({
    queryKey: confluenceKeys.snapshots,
    queryFn: ({ signal }) => api.get<ConfluenceSnapshot[]>(ConfluencePath.snapshots, { signal }),
    refetchInterval: (query) => pollWhileRunning(query.state.data),
  });

export const plansQuery = () =>
  queryOptions({
    queryKey: confluenceKeys.plans,
    queryFn: ({ signal }) => api.get<ConfluencePlan[]>(ConfluencePath.plans, { signal }),
  });

export const planQuery = (planId: string) =>
  queryOptions({
    queryKey: confluenceKeys.plan(planId),
    queryFn: ({ signal }) => api.get<ConfluencePlan>(`${ConfluencePath.plans}/${planId}`, { signal }),
    enabled: Boolean(planId),
  });

export const runsQuery = () =>
  queryOptions({
    queryKey: confluenceKeys.runs,
    queryFn: ({ signal }) => api.get<ConfluenceRun[]>(ConfluencePath.runs, { signal }),
    refetchInterval: (query) => pollWhileRunning(query.state.data),
  });

/** The wiki's block renderers, a macro's possible destination. They change only with a deploy. */
export const renderersQuery = () =>
  queryOptions({
    queryKey: confluenceKeys.renderers,
    queryFn: ({ signal }) => api.get<PageRendererChoice[]>(PAGE_RENDERERS_PATH, { signal }),
    staleTime: Infinity,
  });
