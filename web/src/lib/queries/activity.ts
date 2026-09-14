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
  AuditCatalog,
  AuditEntry,
  AuditSourceValue,
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
  /** Constrains the read to one project — REQUIRED for anyone but an instance admin. */
  projectId?: string;
  entityType?: string;
  entityId?: string;
  actorId?: string;
  /** Rows whose diff touched this field (`assignee`, `permissions`…). */
  changedField?: string;
  source?: AuditSourceValue | "";
  /** ISO dates (inclusive day bounds are applied by the caller). */
  start?: string;
  end?: string;
  /** Trigram free text over the event, the entity and the changed values (spec 123). */
  q?: string;
  includeNoise?: boolean;
  limit?: number;
  offset?: number;
}

const auditWire = (params: AuditParams): Record<string, string | undefined> => ({
  project_id: params.projectId || undefined,
  entity_type: params.entityType || undefined,
  entity_id: params.entityId || undefined,
  actor_id: params.actorId || undefined,
  changed_field: params.changedField || undefined,
  source: params.source || undefined,
  start: params.start || undefined,
  end: params.end || undefined,
  q: params.q || undefined,
  include_noise: params.includeNoise ? "true" : undefined,
  limit: String(params.limit ?? 100),
  offset: String(params.offset ?? 0),
});

/** The audit ledger (newest first). Admins read the instance, project managers one project (403 otherwise). */
export const auditQuery = (params: AuditParams) =>
  queryOptions({
    queryKey: queryKeys.audit(
      Object.fromEntries(
        Object.entries(auditWire(params)).map(([key, value]) => [key, value ?? ""]),
      ),
    ),
    queryFn: ({ signal }) =>
      api.get<AuditEntry[]>(ApiPath.audit, { signal, query: auditWire(params) }),
    retry: false,
    placeholderData: keepPreviousData,
  });

/** The registry's event/entity vocabulary — what the audit filters are built from. */
export const auditCatalogQuery = () =>
  queryOptions({
    queryKey: queryKeys.auditCatalog(),
    queryFn: ({ signal }) => api.get<AuditCatalog>(ApiPath.auditCatalog, { signal }),
    staleTime: 5 * 60_000,
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
