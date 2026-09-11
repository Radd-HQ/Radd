/** Activity/history, related links, version control, link search, audit, backups. */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiItemHistoryPath,
  apiItemLinkSearchPath,
  apiItemVcsLinksPath,
  apiItemWebLinksPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  AuditEntry,
  BackupArtifact,
  BackupRun,
  BackupSchedule,
  BackupStatus,
  ItemHistory,
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

/** Dependency-link / parent-picker typeahead: items across the SERVER
 *  matching `q` (title or number/key), same-project first (spec 80). */
export const linkSearchQuery = (projectId: string, q: string, excludeId?: string, limit?: number) =>
  queryOptions({
    queryKey: queryKeys.linkSearch(projectId, q, limit, excludeId),
    queryFn: ({ signal }) =>
      api.get<ItemLinkSearchResult[]>(apiItemLinkSearchPath(), {
        signal,
        query: {
          project_id: projectId,
          q,
          exclude_id: excludeId || undefined,
          limit: limit !== undefined ? String(limit) : undefined,
        },
      }),
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });

export interface AuditParams {
  entityType?: string;
  actorId?: string;
  /** Free-text match on event type or payload (RADD-884). */
  q?: string;
  limit?: number;
  offset?: number;
}

/** Admin audit trail (newest first) — the events log, filtered. Requires admin (403 handled). */
export const auditQuery = (params: AuditParams) =>
  queryOptions({
    queryKey: queryKeys.audit({
      entityType: params.entityType ?? "",
      actorId: params.actorId ?? "",
      q: params.q ?? "",
      limit: String(params.limit ?? 100),
      offset: String(params.offset ?? 0),
    }),
    queryFn: ({ signal }) =>
      api.get<AuditEntry[]>(ApiPath.audit, {
        signal,
        query: {
          entity_type: params.entityType || undefined,
          actor_id: params.actorId || undefined,
          q: params.q || undefined,
          limit: String(params.limit ?? 100),
          offset: String(params.offset ?? 0),
        },
      }),
    retry: false,
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
