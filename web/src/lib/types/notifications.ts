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
  /** Spec 118: the ambient kinds a SUBSCRIPTION exists to deliver — an issue
   *  filed, an edit that changed neither state nor description, a page created.
   *  Off in every relationship scope by default. */
  created: "created",
  updated: "updated",
  pageCreated: "page_created",
} as const;
export type NotificationTypeValue = (typeof NotificationType)[keyof typeof NotificationType];

/**
 * How a person is connected to the thing an event is about (spec 118).
 *
 * The first three are the matrix's COLUMNS — relationships, which hold or do
 * not and have nothing to point at (`scope_id` is null). The last three are
 * SUBSCRIPTIONS: a row exists because someone named one project, space or team.
 */
export const RuleScope = {
  own: "own",
  participating: "participating",
  teams: "teams",
  project: "project",
  space: "space",
  team: "team",
} as const;
export type RuleScopeValue = (typeof RuleScope)[keyof typeof RuleScope];

/** What one cell of the matrix says. The two channels are independent — `email`
 *  with no inbox row is a real answer, and the one RADD-686 could not express. */
export const Channel = {
  off: "off",
  inbox: "inbox",
  email: "email",
  both: "both",
} as const;
export type ChannelValue = (typeof Channel)[keyof typeof Channel];

/** One row of the matrix, served from the SERVER's vocabulary (spec 118) — the
 *  SPA no longer carries its own label map, which could disagree with the enum
 *  it was describing with nothing to catch it. */
export interface NotificationKind {
  kind: NotificationTypeValue;
  label: string;
  description: string;
  /** Addressed at you by the event itself: resolves through `own` alone, so the
   *  other columns are greyed. */
  personal: boolean;
}

/** One saved rule: a scope, an optional target, and a SPARSE channel map. */
export interface NotificationRule {
  scope: RuleScopeValue;
  scope_id: string | null;
  /** Resolved name of the project/space/team; null for a relationship scope (or
   *  when the target has been deleted). Display only. */
  scope_label: string | null;
  channels: Partial<Record<NotificationTypeValue, ChannelValue>>;
}

/**
 * GET/PUT /notifications/preferences — the caller's whole notification policy
 * (spec 118): the kind vocabulary, the relationship columns, what an unset cell
 * inherits, and the rules they actually saved.
 *
 * PUT is a full replace of `rules`: removing a subscription IS leaving its row
 * out, which is only expressible when the whole set is sent.
 */
export interface NotificationPrefs {
  kinds: NotificationKind[];
  scopes: RuleScopeValue[];
  /** {scope: {kind: channel}} for the relationship columns — the inherited value. */
  defaults: Partial<Record<RuleScopeValue, Partial<Record<NotificationTypeValue, ChannelValue>>>>;
  rules: NotificationRule[];
  email_digest: boolean;
}

/** PUT body — `scope_label` is a read-only display value and is not sent back. */
export interface NotificationPrefsUpdate {
  rules: { scope: RuleScopeValue; scope_id: string | null; channels: Partial<Record<NotificationTypeValue, ChannelValue>> }[];
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
    /** RADD-1297: the comment a commented/mentioned row is about — opens ON it. */
    comment_id?: string;
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
  /** RADD-719 (page_updated / spec 118 page_created): everything the row needs
   *  to render and link without a join — resolved at write time, so a later
   *  rename cannot make the entry lie about what it told you at the time. */
  page_id?: string;
  /** RADD-1233: the permalink key — on every page row, the migration backfilled the old ones. */
  page_number?: number;
  page_slug?: string;
  space_slug?: string;
  title?: string;
  version?: number;
  /** Spec 118 (`updated`): which fields moved — a generic edit notification
   *  with no field names is a line carrying no information. */
  fields?: string[];
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
