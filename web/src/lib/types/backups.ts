/** Backups (spec 99) — instance-admin only. */

/** Why an artifact exists. Only `scheduled` ones are ever auto-pruned. */
export const BackupKind = {
  manual: "manual",
  scheduled: "scheduled",
  preRestore: "pre_restore",
  uploaded: "uploaded",
} as const;
export type BackupKindValue = (typeof BackupKind)[keyof typeof BackupKind];

export const BACKUP_KIND_LABELS: Record<string, string> = {
  manual: "Manual",
  scheduled: "Scheduled",
  pre_restore: "Pre-restore",
  uploaded: "Uploaded",
};

export const RunStatus = {
  pending: "pending",
  running: "running",
  succeeded: "succeeded",
  failed: "failed",
} as const;

/** Stage labels for the progress line while a run is in flight. */
export const RUN_STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  dumping: "Dumping the database",
  packing: "Packing and encrypting",
  verifying: "Verifying the artifact",
  pruning: "Applying retention",
  safety_backup: "Taking a safety backup",
  draining: "Disconnecting clients",
  restoring: "Restoring the database",
  migrating: "Running migrations",
  attachments: "Restoring attachments",
  done: "Done",
};

export interface BackupArtifact {
  name: string;
  size_bytes: number;
  created_at: string;
  kind: string;
  complete: boolean;
  encrypted: boolean;
  key_id: string | null;
  includes_attachments: boolean;
  schema_version: number | null;
  radd_version: string | null;
  created_by: string | null;
  /** Decided server-side, so the UI never offers a restore that would be refused. */
  restorable: boolean;
  problem: string | null;
}

export interface BackupRun {
  id: string;
  kind: string;
  status: string;
  stage: string;
  artifact_name: string | null;
  size_bytes: number | null;
  started_at: string;
  finished_at: string | null;
  error: string | null;
}

/** {kind, minutes | time, weekdays} — shared with automations' scheduled rules. */
export interface BackupScheduleConfig {
  kind: "interval" | "daily" | "weekly";
  minutes?: number;
  time?: string;
  weekdays?: number[];
}

export interface BackupSchedule {
  id: string;
  name: string;
  enabled: boolean;
  config: BackupScheduleConfig;
  include_attachments: boolean;
  keep_last: number | null;
  keep_days: number | null;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
}

export interface BackupTool {
  path: string | null;
  version: string | null;
}

export interface BackupStatus {
  directory: string;
  directory_writable: boolean;
  directory_problem: string | null;
  free_bytes: number | null;
  pg_dump: BackupTool;
  pg_restore: BackupTool;
  tools_problem: string | null;
  encryption_enabled: boolean;
  key_id: string | null;
  key_file: string;
  key_problem: string | null;
  schema_version: number;
  maintenance: boolean;
  next_run_at: string | null;
}
