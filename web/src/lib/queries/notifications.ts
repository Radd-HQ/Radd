/** Notifications, the unread badge poll, and watchers (spec 26). */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  NOTIFICATIONS_POLL_MS,
  apiItemWatchersPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  NotificationList,
  NotificationPrefs,
  WatchersRead,
} from "../types";

/** Inbox page size (RADD-884) — the server pages at ≤200; before this the page
 * hard-capped at the first 100 and older notifications were unreachable. */
export const INBOX_PAGE_SIZE = 100;

/** Full notification list for the Inbox (spec 26), paged (RADD-884). */
export const notificationsQuery = (unread: boolean, page = 1) =>
  queryOptions({
    queryKey: queryKeys.notifications(unread, page),
    queryFn: () =>
      api.get<NotificationList>(ApiPath.notifications, {
        query: {
          unread: unread ? "true" : undefined,
          limit: String(INBOX_PAGE_SIZE),
          offset: String((page - 1) * INBOX_PAGE_SIZE),
        },
      }),
    meta: entityMeta(Entity.notification),
    placeholderData: keepPreviousData,
  });

/**
 * Lightweight unread-count poll behind the sidebar Inbox badge. Kept separate
 * from the list query so the whole inbox isn't refetched every 30s; realtime
 * invalidation (spec 27) makes both instant.
 */
export const notificationsBadgeQuery = queryOptions({
  queryKey: queryKeys.notificationsBadge,
  queryFn: () =>
    api.get<NotificationList>(ApiPath.notifications, {
      query: { unread: "true", limit: "1" },
    }),
  meta: entityMeta(Entity.notification),
  refetchInterval: NOTIFICATIONS_POLL_MS,
});

/**
 * The caller's whole notification policy (spec 118): the kind VOCABULARY and the
 * relationship columns to render, what an unset cell inherits per scope, the
 * scoped rules they saved, and the digest flag. Everything the settings page
 * needs to draw an inheritance-aware matrix without a table of its own — the
 * panel this replaced kept its own label map in TypeScript, so a kind added on
 * the server had no row in the UI and nothing failed.
 *
 * (It was `muted_types` + `email_types`, two per-type lists, until spec 118
 * dropped both columns for `notification_rules`.)
 */
export const notificationPrefsQuery = () =>
  queryOptions({
    queryKey: queryKeys.notificationPrefs,
    queryFn: () => api.get<NotificationPrefs>(ApiPath.notificationPrefs),
  });

/** Watcher list + whether the current user watches (spec 26). */
export const itemWatchersQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemWatchers(itemId),
    queryFn: () => api.get<WatchersRead>(apiItemWatchersPath(itemId)),
    meta: entityMeta(Entity.watcher),
  });
