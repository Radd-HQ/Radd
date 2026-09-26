/** The import plan (spec 100): nine mapping tables plus the run options. */

/**
 * How much attention an inbound Jira field deserves (spec 100).
 *
 * One ordered band replaces spec 90's `is_builtin` + `likely_noise` booleans,
 * which could not express "unused" — so a field no issue has ever filled in
 * scored as ordinary data and sat at the TOP of the grid. On a real instance
 * that is most of the catalog: 337 fields, a couple of dozen with anything in
 * them. Only `in_use` is expanded; the rest are collapsed AND default to ignore.
 */
export const FieldBand = {
  in_use: "in_use",
  noise: "noise", // has values, but is machinery or an org-wide default
  unused: "unused", // no issue carries a value — nothing to import
  builtin: "builtin", // a native Jira column, handled without a mapping
} as const;
export type FieldBandValue = (typeof FieldBand)[keyof typeof FieldBand];

export const FieldAction = {
  ignore: "ignore",
  map: "map",
  create: "create",
  native: "native", // route the value into a native Radd feature (BuiltinTarget)
  builtin: "builtin", // the Jira field IS a standard column, auto-handled
} as const;
export type FieldActionValue = (typeof FieldAction)[keyof typeof FieldAction];

/** Native Radd concepts a Jira field's value can be routed into (spec 90). */
export const BuiltinTarget = {
  team: "team",
  status: "status",
  watchers: "watchers",
  parent: "parent",
  assignee: "assignee",
  labels: "labels",
  cycle: "cycle",
  priority: "priority",
  start_date: "start_date",
  target_date: "target_date",
  points: "points",
} as const;
export type BuiltinTargetValue = (typeof BuiltinTarget)[keyof typeof BuiltinTarget];

/** Where a created custom field lives (spec 90). */
export const FieldScope = { global: "global", project: "project" } as const;
export type FieldScopeValue = (typeof FieldScope)[keyof typeof FieldScope];

/** The Radd field types a "create" mapping can target (matches the server enum). */
export const CreateFieldType = {
  text: "text",
  select: "select",
  multi_select: "multi_select",
  number: "number",
  date: "date",
  user: "user",
} as const;

/** One field's disposition — the wire shape of a mapping row. `create_type` uses
 * the Radd FieldType strings (text/number/date/select/multi_select/user). */
export interface FieldMappingEntry {
  jira_id: string;
  jira_name: string;
  action: FieldActionValue;
  target_key: string;
  create_type: string | null;
  create_name: string;
  create_options: string[] | null;
  create_scope: FieldScopeValue;
  builtin_target: BuiltinTargetValue | null;
  /** Per-value translation: Jira value → Radd value/entity name. */
  value_map: Record<string, string>;
  /** Evidence, so the UI can group rows and say why one is collapsed. */
  band: FieldBandValue;
  band_reason: string;
  populated: number;
  samples: string[];
  /** MAP into a select: add the option values it is missing, rather than dropping them. */
  extend_options: boolean;
  /** Every distinct value the snapshot holds for this field. */
  observed_values: string[];
}

/** What to do with one value of a Jira vocabulary. */
export const VocabAction = { map: "map", create: "create", ignore: "ignore" } as const;
export type VocabActionValue = (typeof VocabAction)[keyof typeof VocabAction];

/** Radd has no component concept, so this is a genuine decision. */
export const ComponentAction = { label: "label", field: "field", ignore: "ignore" } as const;
export type ComponentActionValue = (typeof ComponentAction)[keyof typeof ComponentAction];

/** What to do about a person Jira names that Radd may not know. */
export const UserAction = {
  match: "match", // an existing Radd user
  placeholder: "placeholder", // create a password-less account for them
  fallback: "fallback", // attribute their work to one nominated user
  skip: "skip", // leave their work unattributed
} as const;
export type UserActionValue = (typeof UserAction)[keyof typeof UserAction];

export const USER_ACTION_LABELS: Record<UserActionValue, string> = {
  [UserAction.match]: "Existing user",
  [UserAction.placeholder]: "Create placeholder",
  [UserAction.fallback]: "Attribute to…",
  [UserAction.skip]: "Leave unattributed",
};

interface VocabRow {
  jira: string;
  /** Issues in the snapshot using it. 0 = hidden and ignored by default. */
  count: number;
}

export interface IssueTypeMapping extends VocabRow {
  kind: "epic" | "issue" | "subtask";
  action: VocabActionValue;
  type_name: string;
}

export interface StatusMapping extends VocabRow {
  action: VocabActionValue;
  state_name: string;
  category: "triage" | "backlog" | "todo" | "in_progress" | "done" | "canceled";
}

export interface PriorityMapping extends VocabRow {
  priority: "low" | "normal" | "high" | "blocker";
}

export interface LinkTypeMapping extends VocabRow {
  action: VocabActionValue;
  key: string;
  outward_name: string;
  inward_name: string;
}

export interface UserMapping {
  jira_key: string;
  display_name: string;
  jira_email: string;
  count: number;
  roles: string[];
  action: UserActionValue;
  user_id: string | null;
  placeholder_email: string;
  match_reason: string;
}

export interface SprintMapping extends VocabRow {
  action: VocabActionValue;
  cycle_id: string | null;
  state: string;
  start_date: string;
  end_date: string;
  complete_date: string;
}

export interface VersionMapping extends VocabRow {
  action: VocabActionValue;
  release_id: string | null;
}

export interface ComponentMapping extends VocabRow {
  action: ComponentActionValue;
  target_key: string;
}

export interface PlanMappings {
  fields: FieldMappingEntry[];
  issue_types: IssueTypeMapping[];
  statuses: StatusMapping[];
  priorities: PriorityMapping[];
  link_types: LinkTypeMapping[];
  users: UserMapping[];
  sprints: SprintMapping[];
  versions: VersionMapping[];
  components: ComponentMapping[];
}

/** One mapping table — the tab a run problem's `section` names. */
export type PlanSection = keyof PlanMappings;

/** The tabs, in order, with the label a problem's "Fix in …" button uses. */
export const PLAN_SECTIONS: readonly (readonly [PlanSection, string])[] = [
  ["fields", "Fields"],
  ["issue_types", "Issue types"],
  ["statuses", "Statuses"],
  ["priorities", "Priorities"],
  ["link_types", "Link types"],
  ["users", "People"],
  ["sprints", "Sprints"],
  ["versions", "Versions"],
  ["components", "Components"],
];

export interface PlanOptions {
  quiet: boolean;
  import_comments: boolean;
  import_worklogs: boolean;
  import_attachments: boolean;
  import_history: boolean;
  placeholder_email_domain: string;
}

export interface JiraPlan {
  id: string;
  name: string;
  snapshot_id: string;
  radd_project_id: string | null;
  radd_project_key: string;
  radd_project_name: string;
  mappings: PlanMappings;
  options: PlanOptions;
  provisioned_at: string | null;
  created_at: string;
}

export interface PlanProblem {
  section: string;
  subject: string;
  message: string;
}

export interface PlanValidation {
  ok: boolean;
  problems: PlanProblem[];
}
