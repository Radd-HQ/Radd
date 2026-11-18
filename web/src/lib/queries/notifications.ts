/** Notifications, the unread badge poll, and watchers (spec 26). */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "@radd/plugin-sdk";
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
  RuleScopeValue,
} from "../types";
import type { DirectoryOption } from "@radd/plugin-sdk";

/** Inbox page size (RADD-884) — the server pages at ≤200; before this the page
 * hard-capped at the first 100 and older notifications were unreachable. */
export const INBOX_PAGE_SIZE = 100;

/** How many unread rows the badge's request carries: enough for My Work's
 *  inbox widget, which shows five groups, to read it instead of asking again. */
const BADGE_ROWS = 20;
const BADGE_FRESH_MS = 10_000;

/** The first-page list request under way, if any: its answer carries the unread
 *  count the shell's badge wants (RADD-1564). */
let listInFlight: Promise<NotificationList> | null = null;

/** Full notification list for the Inbox (spec 26), paged (RADD-884). */
export const notificationsQuery = (unread: boolean, page = 1) =>
  queryOptions({
    queryKey: queryKeys.notifications(unread, page),
    queryFn: ({ signal }) => {
      const answer = api.get<NotificationList>(ApiPath.notifications, {
        signal,
        query: {
          unread: unread ? "true" : undefined,
          limit: String(INBOX_PAGE_SIZE),
          offset: String((page - 1) * INBOX_PAGE_SIZE),
        },
      });
      // Only page 1 holds the newest rows, which is what the badge would get.
      if (page === 1) {
        listInFlight = answer;
        const forget = () => {
          if (listInFlight === answer) listInFlight = null;
        };
        answer.then(forget, forget);
      }
      return answer;
    },
    meta: entityMeta(Entity.notification),
    placeholderData: keepPreviousData,
  });

/**
 * The unread count behind the Inbox badge, with the newest few unread rows
 * (RADD-1567): My Work's inbox widget reads this answer instead of sending a
 * request of its own after the shell already has. Kept separate from the list
 * query so the whole inbox isn't refetched every 30s; realtime invalidation
 * (spec 27) makes both instant.
 */
export const notificationsBadgeQuery = queryOptions({
  queryKey: queryKeys.notificationsBadge,
  queryFn: async ({ signal }) => {
    // RADD-1564: on the Inbox the page asks for the list in the same tick, and
    // that answer carries the count. One turn of the event loop lets the page's
    // request start, whichever of the two mounted first.
    await new Promise((resolve) => setTimeout(resolve, 0));
    const pending = listInFlight;
    if (pending) {
      try {
        const list = await pending;
        // RADD-1567: this answer is also what My Work's widget lists, so it is
        // taken from the list only when the list provably holds the newest
        // unread rows; a page of mostly read rows may not.
        const unread = list.notifications.filter((row) => !row.read).slice(0, BADGE_ROWS);
        if (unread.length >= Math.min(list.unread_count, BADGE_ROWS)) {
          return { notifications: unread, unread_count: list.unread_count };
        }
      } catch {
        // The list failed or was cancelled: ask the ordinary way.
      }
    }
    return api.get<NotificationList>(ApiPath.notifications, {
      signal,
      query: { unread: "true", limit: String(BADGE_ROWS) },
    });
  },
  meta: entityMeta(Entity.notification),
  refetchInterval: NOTIFICATIONS_POLL_MS,
  // Fresh for a few seconds, so a reader that mounts after the shell (My Work's
  // widget) takes the answer already here instead of refetching it. A new
  // notification still arrives at once: realtime invalidates, which ignores this.
  staleTime: BADGE_FRESH_MS,
});

/** The caller's whole notification policy (spec 118): the kind vocabulary, the columns, what an
 *  unset cell inherits per scope, the saved rules and the digest flag — so the settings page draws
 *  its matrix without a table of its own. */
export const notificationPrefsQuery = () =>
  queryOptions({
    queryKey: queryKeys.notificationPrefs,
    meta: entityMeta(Entity.role, Entity.project, Entity.docSpace, Entity.team, Entity.group, Entity.member),
    queryFn: ({ signal }) => api.get<NotificationPrefs>(ApiPath.notificationPrefs, { signal }),
  });

/** Watcher list + whether the current user watches (spec 26). */
export const itemWatchersQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemWatchers(itemId),
    queryFn: ({ signal }) => api.get<WatchersRead>(apiItemWatchersPath(itemId), { signal }),
    meta: entityMeta(Entity.watcher),
  });

export const subscriptionOptionsKey = ["subscription-options"] as const;
export const subscriptionOptionsQuery = (scope: RuleScopeValue, q: string, page: number) => queryOptions({
  queryKey: [...subscriptionOptionsKey, scope, q.trim(), page],
  meta: entityMeta(Entity.role, Entity.project, Entity.docSpace, Entity.team, Entity.group, Entity.member),
  queryFn: ({ signal }) => api.getPaged<DirectoryOption>("/notifications/subscription-options", {
    signal, query: { scope, q: q.trim(), limit: "50", offset: String(page * 50) },
  }),
});
