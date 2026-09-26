/** Jira importer wire shapes (specs 90, 100): connections, downloads and runs.
 * The plan's nine mapping tables are in `plan-types.ts`. */

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

/** What a dry run says it would do to one issue. */
export const DryRunAction = { create: "create", update: "update", skip: "skip" } as const;

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
  /** The exact plan this run executed (RADD-1105) — provenance that survives
   * the plan being edited for a redo. */
  plan_snapshot: {
    name?: string;
    radd_project_key?: string;
    radd_project_name?: string;
    mappings?: Record<string, Record<string, { action?: string; target?: string; create_name?: string }>>;
    options?: Record<string, unknown>;
  };
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

// --- what the plan editor reads from the modules that own it ------------------
// Only the fields this page uses, from each owner's public REST read.

/** GET /projects/by-key/{key} (projects). */
export interface TargetProject { id: string; key: string }
/** GET /states?project_id= (workflow). */
export interface TargetState { id: string; name: string; category: string }
/** GET /issue-types?project_id= (itemtypes). */
export interface TargetIssueType { id: string; name: string }
/** GET /teams (teams). */
export interface TargetTeam { id: string; name: string }
/** GET /users — the ADMIN directory (auth), which carries every account's address. */
export interface TargetUser { id: string; name: string; email: string }
