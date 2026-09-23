import type { Notification } from "./types";

/**
 * RADD-1294: consecutive notifications that say the same thing — same kind, same
 * person, same issue or page — collapse into one inbox row. Fourteen rows of
 * "Hussein Jarrar edited Shared page" is one fact told fourteen times.
 *
 * Only NEIGHBOURS merge, so the inbox stays in time order: an edit, a comment,
 * then more edits is three rows, not two.
 */
export interface NotificationBurst {
  /** The newest of the run — what the row shows and opens. */
  lead: Notification;
  /** Every notification in the run, lead first. */
  members: Notification[];
}

function burstKey(notification: Notification): string {
  const target = notification.item_id ?? notification.detail.page_id ?? "";
  return `${notification.type}|${notification.actor?.id ?? ""}|${target}`;
}

export function groupNotificationBursts(notifications: readonly Notification[]): NotificationBurst[] {
  const bursts: NotificationBurst[] = [];
  for (const notification of notifications) {
    const last = bursts[bursts.length - 1];
    const target = notification.item_id ?? notification.detail.page_id;
    if (last && target && burstKey(last.lead) === burstKey(notification)) {
      last.members.push(notification);
    } else {
      bursts.push({ lead: notification, members: [notification] });
    }
  }
  return bursts;
}
