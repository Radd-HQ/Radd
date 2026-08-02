/** Automation rules (specs 20/58/66/69). */
import type { CustomFieldValue } from "./items";
// ---------------------------------------------------------------------------
// Automations (spec 20 — /automations). Global rules that react to an
// item event, match an SLQ condition, and apply an ordered list of actions.
// ---------------------------------------------------------------------------

/** A rule's trigger is an event-type string from GET /automations/catalog
 * ("item.updated", "comment.created", …) — or a sentinel. `manual` rules
 * never fire from events: they run on demand from the editor's `/` quick-action
 * menu (POST /automations/{id}/run). */
export const MANUAL_TRIGGER = "manual";

/** Spec 69: the schedule sentinel — the rule fires from the scheduler clock
 * instead of an event, driven by its `schedule` config. */
export const SCHEDULE_TRIGGER = "schedule";

/** Shape of a scheduled rule's `schedule` (spec 69, mirror of ScheduleKind). */
export const ScheduleKind = {
  interval: "interval",
  daily: "daily",
  weekly: "weekly",
} as const;
export type ScheduleKindValue = (typeof ScheduleKind)[keyof typeof ScheduleKind];

/** interval: {minutes >= 5}; daily: {time "HH:MM"}; weekly: {time, weekdays
 * (0=Mon, non-empty)}. Times run on the server's scheduler timezone. */
export interface RuleSchedule {
  kind: ScheduleKindValue;
  minutes?: number | null;
  time?: string | null;
  weekdays?: number[] | null;
}

/** One subscribable event type, from GET /automations/catalog (spec 58). */
export interface TriggerInfo {
  event_type: string;
  label: string;
  group: string;
  /** A target item resolves — the SLQ condition + item actions apply to it. */
  item_scoped: boolean;
  /** The payload carries a field diff (changed-field/old/new subjects work). */
  has_changes: boolean;
}

export const ConditionSubject = {
  actor: "actor",
  changedField: "changed_field",
  oldValue: "old_value",
  newValue: "new_value",
  stateCategory: "state_category",
  payload: "payload",
} as const;
export type ConditionSubjectValue = (typeof ConditionSubject)[keyof typeof ConditionSubject];

export const ConditionGroupOp = { all: "all", any: "any", none: "none" } as const;
export type ConditionGroupOpValue =
  (typeof ConditionGroupOp)[keyof typeof ConditionGroupOp];

/** One leaf condition on the triggering event (spec 58). */
export interface EventCondition {
  subject: ConditionSubjectValue;
  /** Field name (old/new value) or dotted payload path — where the subject needs one. */
  qualifier?: string | null;
  operator: string;
  value?: string | number | boolean | string[] | null;
}

/** A nestable all/any/none group of conditions. */
export interface ConditionGroup {
  op: ConditionGroupOpValue;
  conditions: (ConditionGroup | EventCondition)[];
}

export interface SubjectInfo {
  key: ConditionSubjectValue;
  label: string;
  needs_qualifier: boolean;
  qualifier_hint: string;
  requires_changes: boolean;
}

export interface OperatorInfo {
  key: string;
  label: string;
  needs_value: boolean;
  list_value: boolean;
}

/** GET /automations/catalog — everything the rule builder renders from. */
export interface AutomationCatalog {
  triggers: TriggerInfo[];
  subjects: SubjectInfo[];
  operators: OperatorInfo[];
  manual_trigger: string;
  /** Spec 69: the "On a schedule" sentinel + the schedule kinds it offers. */
  schedule_trigger: string;
  schedule_kinds: { key: ScheduleKindValue; label: string }[];
}

/** What a matching rule does to an item (mirror of backend `ActionType`). */
export const ActionType = {
  setState: "set_state",
  setPriority: "set_priority",
  setAssignee: "set_assignee",
  setTeam: "set_team",
  addLabel: "add_label",
  removeLabel: "remove_label",
  setCycle: "set_cycle",
  setRelease: "set_release",
  setCustomField: "set_custom_field",
  addComment: "add_comment",
  // Universal actions (spec 58b) — run with or without a target item; their
  // text params accept {{event_type}}/{{actor.*}}/{{payload.*}}/{{item.*}}.
  createItem: "create_item",
  sendWebhook: "send_webhook",
  postChat: "post_chat",
  notifyUser: "notify_user",
  sendEmail: "send_email",
} as const;
export type ActionTypeValue = (typeof ActionType)[keyof typeof ActionType];

/**
 * Role values the send_email action's `to` param may name (spec 66) — anything
 * else is a literal address. Roles resolve against the event's target item.
 */
export const EmailRecipient = {
  reporter: "reporter",
  assignee: "assignee",
  contact: "contact",
} as const;
export type EmailRecipientValue = (typeof EmailRecipient)[keyof typeof EmailRecipient];

/**
 * One rule action as sent to the API — `{type, params}` where params is
 * type-specific (state name / priority / assignee email / team|cycle name /
 * label / release version / {key,value} / {body,visibility}). Names resolve per
 * item at apply time; `"none"` clears assignee/team/cycle/release.
 */
export interface RuleAction {
  type: ActionTypeValue;
  params: Record<string, CustomFieldValue>;
}

/** GET /automations — actions arrive opaque (`{type, params}`). */
/** Member-visible slice of an enabled manual rule — the `/` menu's custom actions. */
export interface RunnableRule {
  id: string;
  name: string;
}

export interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  trigger: string;
  event_conditions: ConditionGroup | null;
  condition_slq: string;
  actions: RuleAction[];
  position: number;
  /** Spec 69: present iff trigger === "schedule"; the run stamps come from the
   * scheduler's bookkeeping (null for event/manual rules). */
  schedule: RuleSchedule | null;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RuleCreate {
  name: string;
  enabled?: boolean;
  trigger: string;
  event_conditions?: ConditionGroup | null;
  condition_slq?: string;
  actions: RuleAction[];
  position?: number;
  schedule?: RuleSchedule | null;
}

/** PATCH /automations/{id} — omitted keys untouched (null clears conditions/schedule). */
export interface RuleUpdate {
  name?: string;
  enabled?: boolean;
  trigger?: string;
  event_conditions?: ConditionGroup | null;
  condition_slq?: string;
  actions?: RuleAction[];
  position?: number;
  schedule?: RuleSchedule | null;
}

/** One action's dry-run outcome (POST /automations/{id}/test). */
export interface ActionPreview {
  type: ActionTypeValue;
  params: Record<string, unknown>;
  /** False when a named target no longer resolves (the engine would skip it). */
  resolves: boolean;
  detail: string;
}

/** POST /automations/{id}/test result — whether the item matched + per-action preview. */
export interface RuleTestResult {
  rule_id: string;
  item_id: string;
  matched: boolean;
  would_apply: ActionPreview[];
}
