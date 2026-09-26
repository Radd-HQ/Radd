/** Shared VCS connection protocol; each connector owns its endpoint declarations. */
export type HostConnection = {
  id: string;
  name: string;
  base_url: string;
  active: boolean;
  verify_ssl: boolean;
  has_token: boolean;
  has_secret: boolean;
  repo_count: number;
  created_at: string;
};

export type HostRepo = {
  enabled: boolean;
  link_all_projects: boolean;
  id: string;
  connection_id: string;
  full_name: string;
  project_id: string | null;
  default_branch: string;
  last_backfill_at: string | null;
  /** RADD-1258: the work category a worklog mirrored from this repository's
   *  MRs/PRs carries; null = the instance's Development. */
  time_category_id: string | null;
  /** RADD-1321: copy MR/PR time into worklogs — off until switched on. */
  mirror_time: boolean;
  /** RADD-1369: move issues a merged change names to their project's waiting state. */
  move_on_merge: boolean;
  /** RADD-1369: record a published release in the default project and sweep. */
  publish_on_release: boolean;
  created_at: string;
};

export type HostConnectionTest = { ok: boolean; version: string; detail: string };


export type HostBackfillReport = {
  branches: number;
  pull_requests: number;
  commits: number;
  linked: number;
  unknown_keys: string[];
  worklogs?: Record<string, unknown>;
  errors?: string[];
};

/** RADD-1258 — how a provider account was tied to a Radd user. */
export const VcsMatchedBy = { email: "email", manual: "manual" } as const;
export type VcsMatchedByValue = (typeof VcsMatchedBy)[keyof typeof VcsMatchedBy];

/** One row of a connection's identity map (`GET /vcs/{provider}/connections/{id}/identities`). */
export interface VcsUserLink {
  id: string;
  provider: string;
  connection_id: string;
  external_username: string;
  user_id: string;
  user_name: string;
  matched_by: VcsMatchedByValue;
  created_at: string;
}

/** A provider account whose time entries are parked because no Radd user
 *  matched it — derived from the parked rows, so nothing to keep in sync. */
export interface VcsUnmatchedAuthor {
  external_username: string;
  external_email: string;
  pending_entries: number;
  pending_seconds: number;
  pending_duration: string;
  last_seen_at: string | null;
}

export interface VcsUserLinkSet {
  external_username: string;
  user_id: string;
}

export interface VcsReplayResult {
  replayed: number;
}


