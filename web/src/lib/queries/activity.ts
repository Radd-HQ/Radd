/** Activity/history, related links, version control, link search, audit, backups. */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "@radd/plugin-sdk";
import {
  ApiPath,
  apiItemHistoryPath,
  apiItemLinkSearchPath,
  apiItemVcsLinksPath,
  apiItemWebLinksPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  BackupArtifact,
  BackupRun,
  BackupSchedule,
  BackupStatus,
  ItemHistory,
  ItemKindValue,
  ItemLinkSearchResult,
  VcsLink,
  WebLink,
} from "../types";

// ---------------------------------------------------------------------------
// Activity / history, related links, version control, audit
// ---------------------------------------------------------------------------

/**
 * An item's activity feed (History tab): field changes + comments/worklogs/links.
 * Tagged with every entity that can appear in it, so any of those mutations
 * refresh it live (see lib/cache.ts).
 */
export const itemHistoryQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemHistory(itemId),
    meta: entityMeta(
      Entity.item,
      Entity.comment,
      Entity.worklog,
      Entity.webLink,
      Entity.vcsLink,
    ),
    queryFn: ({ signal }) => api.get<ItemHistory>(apiItemHistoryPath(itemId), { signal }),
  });

/** External/related links on an item (docs, designs, references). */
export const itemWebLinksQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemWebLinks(itemId),
    meta: entityMeta(Entity.webLink),
    queryFn: ({ signal }) => api.get<WebLink[]>(apiItemWebLinksPath(itemId), { signal }),
  });

/** Version-control references on an item (branches, commits, MRs/PRs). */
export const itemVcsLinksQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemVcsLinks(itemId),
    meta: entityMeta(Entity.vcsLink),
    queryFn: ({ signal }) => api.get<VcsLink[]>(apiItemVcsLinksPath(itemId), { signal }),
  });

/** The parent picker's narrowing of the typeahead (RADD-1471): `kind` is the
 *  kind the ladder requires (an issue picks epics, a subtask picks issues);
 *  `unparented` keeps only items with no parent (an epic adopting issues). */
export interface LinkSearchFilters {
  kind?: ItemKindValue;
  unparented?: boolean;
  /** Only the anchor project's items — a subtask's parent issue lives there (RADD-1492). */
  sameProject?: boolean;
}

/** Dependency-link / parent-picker typeahead: items across the SERVER
 *  matching `q` (title or number/key), same-project first (spec 80). */
export const linkSearchQuery = (
  projectId: string,
  q: string,
  excludeId?: string,
  limit?: number,
  filters: LinkSearchFilters = {},
) =>
  queryOptions({
    queryKey: queryKeys.linkSearch(projectId, q, limit, excludeId, filters.kind, filters.unparented, filters.sameProject),
    queryFn: ({ signal }) =>
      api.get<ItemLinkSearchResult[]>(apiItemLinkSearchPath(), {
        signal,
        query: {
          project_id: projectId,
          q,
          exclude_id: excludeId || undefined,
          limit: limit !== undefined ? String(limit) : undefined,
          kind: filters.kind,
          unparented: filters.unparented ? "true" : undefined,
          same_project: filters.sameProject ? "true" : undefined,
        },
      }),
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });

// --- backups (spec 99) — instance admin only ---

/** Directory, tools, key and next run. Polled while a run is in flight. */
export const backupStatusQuery = () =>
  queryOptions({
    queryKey: queryKeys.backupStatus(),
    queryFn: ({ signal }) => api.get<BackupStatus>(`${ApiPath.backups}/status`, { signal }),
    retry: false,
  });

/** The artifact inventory — read from DISK server-side, never from a table. */
export const backupsQuery = () =>
  queryOptions({
    queryKey: queryKeys.backups(),
    queryFn: ({ signal }) => api.get<BackupArtifact[]>(ApiPath.backups, { signal }),
    retry: false,
  });

export const backupSchedulesQuery = () =>
  queryOptions({
    queryKey: queryKeys.backupSchedules(),
    queryFn: ({ signal }) => api.get<BackupSchedule[]>(`${ApiPath.backups}/schedules`, { signal }),
    retry: false,
  });

/** One run, polled for progress. A restore reverts the run table, so this 404s
 *  once a restore finishes — `/backups/status` is the completion signal. */
export const backupRunQuery = (runId: string | null) =>
  queryOptions({
    queryKey: queryKeys.backupRun(runId ?? ""),
    queryFn: ({ signal }) => api.get<BackupRun>(`${ApiPath.backups}/runs/${runId}`, { signal }),
    enabled: Boolean(runId),
    retry: false,
  });
