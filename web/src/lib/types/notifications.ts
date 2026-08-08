/** Notifications + watchers (spec 26). */
// ---------------------------------------------------------------------------
// Notifications + watchers (notify module — spec 26)
// ---------------------------------------------------------------------------

export const NotificationType = {
  assigned: "assigned",
  mentioned: "mentioned",
  stateChanged: "state_changed",
  commented: "commented",
  slaBreach: "sla_breach",
  /** Spec 69: the pre-breach sla.due_soon warning — muteable like the rest. */
  slaDueSoon: "sla_due_soon",
  /** Spec 58b: an automation rule's notify_user action — detail: {message, rule}. */
  automation: "automation",
  /** Spec 71: approval requests (to approvers) + decisions (to the requester) —
   * detail: {action: requested|approved|declined, to_state, required}. */
  approval: "approval",
  /** RADD-719: a watched wiki page changed. Carries no item — `detail` holds the
   *  page's slugs so the row can link without a join. */
  pageUpdated: "page_updated",
  /** RADD-978: someone shared an issue with you (spec 72's direct user
   *  participant). No detail — the item key/title carry the whole line. A TEAM
   *  add produces nothing: team rows resolve live at fan-out and are ambient. */
  participantAdded: "participant_added",
} as const;
export type NotificationTypeValue = (typeof NotificationType)[keyof typeof NotificationType];

/**
 * GET/PUT /notifications/preferences — the caller's per-type channel matrix
 * (RADD-686). Inbox = NOT in `muted_types`; email = in `email_types`.
 *
 * Email requires inbox: a muted type never becomes a notification row, and rows
 * are what get mailed, so the server drops muted entries from `email_types` on
 * save and the PUT response is always the normalised pair. PUT is a full
 * replace — every field is required.
 */
export interface NotificationPrefs {
  muted_types: NotificationTypeValue[];
  email_types: NotificationTypeValue[];
  email_digest: boolean;
}

export interface Notification {
  id: string;
  type: NotificationTypeValue;
  item_id: string | null;
  item_key: string | null;
  item_title: string | null;
  actor: { id: string; name: string } | null;
  /** Type-specific extras: excerpt, from/to state names, source, visibility, SLA info. */
  detail: {
    excerpt?: string;
    from?: string | null;
    to?: string | null;
    source?: string;
    visibility?: string;
    policy?: string;
    kind?: string;
    due_at?: string | null;
    /** Spec 69 sla_due_soon notifications: active time left when warned. */
    remaining_seconds?: number | null;
    /** Spec 58b automation notifications: the rendered message + rule name. */
    message?: string;
    rule?: string;
    /** Spec 71 approval notifications: what happened + the gated target state. */
    action?: string;
    to_state?: string;
    required?: number;
    approved_count?: number;
  /** RADD-719 (page_updated): everything the row needs to render and link
   *  without a join — resolved at write time, so a later rename cannot make the
   *  entry lie about what it told you at the time. */
  page_id?: string;
  page_slug?: string;
  space_slug?: string;
  title?: string;
  version?: number;
  };
  read: boolean;
  created_at: string;
}

export interface NotificationList {
  notifications: Notification[];
  unread_count: number;
}

export interface WatchersRead {
  watching: boolean;
  watchers: { id: string; name: string }[];
}
