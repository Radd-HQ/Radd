/**
 * Wire shapes for the Confluence importer (spec 117).
 *
 * These mirror `server/src/radd/modules/confluenceimport/{types,schemas}.py`. A
 * wire constant is a contract with no compiler behind it (RADD-701): renaming a
 * value here without renaming it there type-checks, builds, and silently does
 * nothing — so every enum below is spelled exactly as the server spells it.
 */

export const ConfluenceAuthMode = {
  pat: "pat",
  basic: "basic",
} as const;
export type ConfluenceAuthMode = (typeof ConfluenceAuthMode)[keyof typeof ConfluenceAuthMode];

/** A space, a section and its descendants, or an explicit set of pages. */
export const ConfluenceScopeKind = {
  space: "space",
  subtree: "subtree",
  pages: "pages",
} as const;
export type ConfluenceScopeKind = (typeof ConfluenceScopeKind)[keyof typeof ConfluenceScopeKind];

export const ConfluenceMacroAction = {
  native: "native",
  extension: "extension",
  unsupported: "unsupported",
  strip: "strip",
  ignore: "ignore",
} as const;
export type ConfluenceMacroAction = (typeof ConfluenceMacroAction)[keyof typeof ConfluenceMacroAction];

export const ConfluenceUnresolvedPrincipal = {
  fail: "fail",
  map_to: "map_to",
} as const;
export type ConfluenceUnresolvedPrincipal =
  (typeof ConfluenceUnresolvedPrincipal)[keyof typeof ConfluenceUnresolvedPrincipal];

export type ConfluenceMappingSection =
  | "spaces"
  | "macros"
  | "users"
  | "groups"
  | "labels"
  | "jira_links";

export const CONFLUENCE_SNAPSHOT_STAGES = [
  "pending", "spaces", "tree", "bodies", "versions",
  "comments", "restrictions", "attachments", "done", "failed", "canceled",
] as const;
export type ConfluenceSnapshotStage = (typeof CONFLUENCE_SNAPSHOT_STAGES)[number];

export const CONFLUENCE_RUN_STAGES = [
  "pending", "provision", "spaces", "pages", "bodies", "attachments",
  "comments", "restrictions", "versions", "relink", "done", "failed", "canceled",
] as const;
export type ConfluenceRunStage = (typeof CONFLUENCE_RUN_STAGES)[number];

export const CONFLUENCE_TERMINAL_STAGES = new Set(["done", "failed", "canceled"]);

export const CONFLUENCE_STAGE_LABELS: Record<string, string> = {
  pending: "Queued",
  spaces: "Spaces",
  tree: "Page tree",
  pages: "Pages",
  bodies: "Content",
  versions: "History",
  comments: "Comments",
  restrictions: "Restrictions",
  attachments: "Attachments",
  provision: "Preparing",
  relink: "Linking",
  done: "Done",
  failed: "Failed",
  canceled: "Canceled",
};

export interface ConfluenceConnection {
  id: string;
  name: string;
  base_url: string;
  auth_mode: ConfluenceAuthMode;
  username: string;
  has_credential: boolean;
  verify_ssl: boolean;
  is_default: boolean;
  source: string;
  external_source: string;
}

export interface ConfluenceStatus {
  configured: boolean;
  ok: boolean;
  detail: string;
  connection_id: string | null;
  user: string;
}

export interface ConfluenceSpace {
  key: string;
  name: string;
  id: string;
  description: string;
}

export interface ConfluencePageNode {
  id: string;
  title: string;
  parent_id: string | null;
  space_key: string;
  position: number;
  version: number;
}

export interface ConfluenceProblem {
  kind: string;
  message: string;
  subject: string;
  detail: string;
  section: ConfluenceMappingSection | null;
  mapping_key: string;
}

export interface ConfluenceSnapshot {
  id: string;
  name: string;
  connection_id: string | null;
  scope: { kind: ConfluenceScopeKind; space_key: string; root_page_id: string; page_ids: string[] };
  external_source: string;
  base_url: string;
  include_history: boolean;
  history_limit: number | null;
  include_attachments: boolean;
  include_comments: boolean;
  stage: ConfluenceSnapshotStage;
  counts: Record<string, number>;
  problems: ConfluenceProblem[];
  page_count: number;
  byte_size: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface ConfluenceSpaceMapping {
  key: string;
  name: string;
  count: number;
  action: "create" | "map" | "ignore";
  space_id: string | null;
  target_name: string;
}

export interface ConfluenceMacroMapping {
  name: string;
  count: number;
  action: ConfluenceMacroAction;
  extension: string;
  sample_page: string;
  reason: string;
}

export interface ConfluenceUserMapping {
  username: string;
  display_name: string;
  email: string;
  count: number;
  action: "map" | "create" | "ignore";
  user_id: string | null;
}

export interface ConfluenceGroupMapping {
  name: string;
  count: number;
  action: "identity" | "map" | "fail";
  group_id: string | null;
  team_id: string | null;
  resolved_dn: string;
}

export interface ConfluenceLabelMapping {
  name: string;
  count: number;
  action: "create" | "map" | "ignore";
  target: string;
}

export interface ConfluenceJiraLinkMapping {
  project_key: string;
  count: number;
  action: "resolve" | "external" | "ignore";
  radd_project_key: string;
}

export interface ConfluencePlanMappings {
  spaces: ConfluenceSpaceMapping[];
  macros: ConfluenceMacroMapping[];
  users: ConfluenceUserMapping[];
  groups: ConfluenceGroupMapping[];
  labels: ConfluenceLabelMapping[];
  jira_links: ConfluenceJiraLinkMapping[];
}

export interface ConfluencePlanOptions {
  quiet: boolean;
  include_history: boolean;
  history_limit: number | null;
  import_comments: boolean;
  import_attachments: boolean;
  import_restrictions: boolean;
  unresolved_principal: ConfluenceUnresolvedPrincipal;
  unresolved_group_id: string | null;
  unresolved_team_id: string | null;
}

export interface ConfluencePlan {
  id: string;
  name: string;
  snapshot_id: string;
  mappings: ConfluencePlanMappings;
  options: ConfluencePlanOptions;
  provisioned_at: string | null;
}

export interface ConfluencePlanProblem {
  section: ConfluenceMappingSection;
  subject: string;
  message: string;
}

export interface ConfluenceRun {
  id: string;
  plan_id: string | null;
  snapshot_id: string | null;
  kind: string;
  dry_run: boolean;
  stage: ConfluenceRunStage;
  counts: Record<string, number>;
  problems: ConfluenceProblem[];
  report: { rows?: { title: string; space: string; action: string }[]; truncated?: boolean };
  started_at: string | null;
  finished_at: string | null;
}

export interface ConfluenceRollbackPreflight {
  total: number;
  by_entity: Record<string, number>;
  edited_since: number;
}

/** Count keys worth showing, in the order a person reads them. */
export const CONFLUENCE_COUNT_LABELS: Record<string, string> = {
  spaces_created: "Spaces",
  spaces_reused: "Spaces reused",
  pages_created: "Pages created",
  pages_updated: "Pages updated",
  pages_blocked: "Blocked",
  pages_skipped: "Skipped",
  attachments: "Attachments",
  comments: "Comments",
  versions: "Versions",
  restrictions: "Restrictions",
  labels: "Labels",
  problems: "Problems",
  bodies: "Pages downloaded",
  pages_found: "Pages found",
  restricted_pages: "Restricted",
};

export const CONFLUENCE_SECTION_LABELS: Record<ConfluenceMappingSection, string> = {
  spaces: "Spaces",
  macros: "Macros",
  users: "People",
  groups: "Restrictions",
  labels: "Labels",
  jira_links: "Jira links",
};
