/** Jira import wizard types (spec 90). */
// --- Jira import wizard (spec 90) --------------------------------------------

export interface JiraConnectionStatus {
  configured: boolean; // at least one connection row exists
  ok: boolean;
  account: string;
  auth_mode: string; // "pat" | "basic" | "none"
  error: string;
  connection_id: string | null;
  connection_name: string;
}

// --- connections (spec 100) --------------------------------------------------

/** How Radd authenticates to a Jira instance. Jira DC accepts both. */
export const JiraAuthMode = {
  pat: "pat", // personal access token, sent as a Bearer header
  basic: "basic", // username + password
} as const;
export type JiraAuthModeValue = (typeof JiraAuthMode)[keyof typeof JiraAuthMode];

export const JIRA_AUTH_MODE_LABELS: Record<JiraAuthModeValue, string> = {
  [JiraAuthMode.pat]: "Personal access token",
  [JiraAuthMode.basic]: "Username + password",
};

/** Short forms for the connections table, where the full labels force it to scroll. */
export const JIRA_AUTH_MODE_SHORT: Record<JiraAuthModeValue, string> = {
  [JiraAuthMode.pat]: "Token",
  [JiraAuthMode.basic]: "Basic",
};

/** Where the row came from. An env-seeded connection is still fully editable. */
export const JiraConnectionSource = {
  env: "env",
  user: "user",
} as const;
export type JiraConnectionSourceValue =
  (typeof JiraConnectionSource)[keyof typeof JiraConnectionSource];

/** The credential is never returned — only whether one is stored. */
export interface JiraConnection {
  id: string;
  name: string;
  base_url: string;
  auth_mode: JiraAuthModeValue;
  username: string;
  verify_ssl: boolean;
  is_default: boolean;
  source: JiraConnectionSourceValue;
  has_credential: boolean;
  created_at: string;
}

// --- snapshots (spec 100) ----------------------------------------------------

/** Where a download is. The order IS the pipeline. */
export const SnapshotStage = {
  pending: "pending",
  catalogs: "catalogs", // the instance's own field/type/status/priority vocabularies
  issues: "issues",
  comments: "comments", // backfill any list Jira truncated in /search
  worklogs: "worklogs",
  history: "history",
  attachments: "attachments",
  done: "done",
  failed: "failed",
  canceled: "canceled",
} as const;
export type SnapshotStageValue = (typeof SnapshotStage)[keyof typeof SnapshotStage];

export const SNAPSHOT_STAGE_LABELS: Record<SnapshotStageValue, string> = {
  [SnapshotStage.pending]: "Queued",
  [SnapshotStage.catalogs]: "Reading Jira's schema",
  [SnapshotStage.issues]: "Downloading issues",
  [SnapshotStage.comments]: "Backfilling comments",
  [SnapshotStage.worklogs]: "Backfilling worklogs",
  [SnapshotStage.history]: "Backfilling history",
  [SnapshotStage.attachments]: "Downloading attachments",
  [SnapshotStage.done]: "Cached",
  [SnapshotStage.failed]: "Failed",
  [SnapshotStage.canceled]: "Canceled",
};

export const TERMINAL_SNAPSHOT_STAGES: readonly SnapshotStageValue[] = [
  SnapshotStage.done,
  SnapshotStage.failed,
  SnapshotStage.canceled,
];

/** One structured failure: the reason, plus the subject it happened TO. */
export interface JiraProblem {
  kind: string;
  message: string;
  subject: string;
  detail: string;
  /** The mapping tab that would fix it, and the row within it. */
  section: string;
  mapping_key: string;
}

export interface JiraSnapshot {
  id: string;
  connection_id: string | null;
  name: string;
  jira_project_key: string;
  jql: string;
  include_attachments: boolean;
  include_history: boolean;
  stage: SnapshotStageValue;
  counts: Record<string, number>;
  problems: JiraProblem[];
  issue_count: number;
  byte_size: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface SnapshotStartInput {
  name: string;
  jira_project_key: string;
  jql: string;
  connection_id: string | null;
  include_attachments: boolean;
  include_history: boolean;
}

export interface JiraConnectionInput {
  name: string;
  base_url: string;
  auth_mode: JiraAuthModeValue;
  username: string;
  /** Empty on edit means "keep the stored credential". */
  credential: string;
  verify_ssl: boolean;
  is_default: boolean;
}

export interface JiraProject {
  key: string;
  name: string;
  id: string;
  project_type: string;
}

export const InferredType = {
  text: "text",
  select: "select",
  multi_select: "multi_select",
  number: "number",
  date: "date",
  user: "user",
  unknown: "unknown",
} as const;
export type InferredTypeValue = (typeof InferredType)[keyof typeof InferredType];

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

export interface InferredField {
  jira_id: string;
  name: string;
  inferred_type: InferredTypeValue;
  populated: number;
  sample_count: number;
  populate_rate: number;
  is_builtin: boolean;
  distinct_count: number;
  dominant_ratio: number;
  band: FieldBandValue;
  band_reason: string;
  schema_key: string;
  samples: string[];
  distinct_values: string[] | null;
}

export interface JiraPreview {
  total: number;
  sampled: number;
  fields: InferredField[];
}

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

// --- the plan: nine mapping tables (spec 100) --------------------------------

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

// --- runs (spec 100) ---------------------------------------------------------

export const RunKind = { dry_run: "dry_run", import: "import", rollback: "rollback" } as const;
export type RunKindValue = (typeof RunKind)[keyof typeof RunKind];

export const JiraRunStage = {
  pending: "pending",
  provision: "provision",
  items: "items",
  parents: "parents",
  links: "links",
  comments: "comments",
  worklogs: "worklogs",
  attachments: "attachments",
  history: "history",
  relink: "relink",
  done: "done",
  failed: "failed",
  canceled: "canceled",
} as const;
export type JiraRunStageValue = (typeof JiraRunStage)[keyof typeof JiraRunStage];

export const JIRA_RUN_STAGE_LABELS: Record<JiraRunStageValue, string> = {
  [JiraRunStage.pending]: "Queued",
  [JiraRunStage.provision]: "Creating targets",
  [JiraRunStage.items]: "Importing issues",
  [JiraRunStage.parents]: "Resolving parents",
  [JiraRunStage.links]: "Resolving links",
  [JiraRunStage.comments]: "Comments",
  [JiraRunStage.worklogs]: "Worklogs",
  [JiraRunStage.attachments]: "Attachments",
  [JiraRunStage.history]: "History",
  [JiraRunStage.relink]: "Relinking",
  [JiraRunStage.done]: "Done",
  [JiraRunStage.failed]: "Failed",
  [JiraRunStage.canceled]: "Canceled",
};

export const TERMINAL_JIRA_RUN_STAGES: readonly JiraRunStageValue[] = [
  JiraRunStage.done,
  JiraRunStage.failed,
  JiraRunStage.canceled,
];

export interface DryRunRow {
  jira_key: string;
  radd_key: string;
  action: string;
  reason: string;
  title: string;
  comments: number;
  worklogs: number;
  links: number;
}

export interface JiraRun {
  id: string;
  plan_id: string | null;
  snapshot_id: string | null;
  project_id: string | null;
  kind: RunKindValue;
  dry_run: boolean;
  stage: JiraRunStageValue;
  counts: Record<string, number>;
  problems: JiraProblem[];
  report: { rows?: DryRunRow[]; truncated?: boolean; would_provision?: Record<string, number> };
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface RollbackPreflight {
  total: number;
  by_entity: Record<string, number>;
  edited_since: string[];
}

export interface PendingSummary {
  total: number;
  by_project: Record<string, number>;
  resolved: number;
}

export interface MappingProblem {
  jira_id: string;
  message: string;
}

export interface ValidateMappingsResponse {
  ok: boolean;
  problems: MappingProblem[];
}

export interface ImportPlan {
  id: string;
  name: string;
  jira_project_key: string;
  jql: string;
  radd_project_key: string;
  radd_project_name: string;
  field_mappings: FieldMappingEntry[];
  created_at: string;
}

export const ImportStage = {
  pending: "pending",
  fields: "fields",
  issues: "issues",
  links: "links",
  done: "done",
  failed: "failed",
} as const;
export type ImportStageValue = (typeof ImportStage)[keyof typeof ImportStage];

export interface ImportRun {
  id: string;
  plan_id: string | null;
  jira_project_key: string;
  jql: string;
  radd_project_key: string;
  radd_project_name: string;
  /** The mapping snapshot this run used — replayed by "Redo" to re-open the wizard. */
  field_mappings: FieldMappingEntry[];
  stage: ImportStageValue;
  counts: Record<string, number>;
  errors: string[];
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}
