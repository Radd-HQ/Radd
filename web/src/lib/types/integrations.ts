/** Related/external links (weblinks) + version-control references (vcs). */
// ---------------------------------------------------------------------------
// Related / external links (weblinks module)
// ---------------------------------------------------------------------------

export const WebLinkCategory = {
  document: "document",
  design: "design",
  spec: "spec",
  external: "external",
  other: "other",
} as const;
export type WebLinkCategoryValue = (typeof WebLinkCategory)[keyof typeof WebLinkCategory];

export interface WebLink {
  id: string;
  item_id: string;
  url: string;
  title: string;
  category: WebLinkCategoryValue;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface WebLinkCreate {
  url: string;
  title?: string;
  category?: WebLinkCategoryValue;
}

export interface WebLinkUpdate {
  url?: string;
  title?: string;
  category?: WebLinkCategoryValue;
}

// ---------------------------------------------------------------------------
// Version control references (vcs module)
// ---------------------------------------------------------------------------

export const VcsRefType = {
  branch: "branch",
  commit: "commit",
  merge_request: "merge_request",
  pull_request: "pull_request",
} as const;
export type VcsRefTypeValue = (typeof VcsRefType)[keyof typeof VcsRefType];

export const VcsProvider = {
  manual: "manual",
  gitlab: "gitlab",
  github: "github",
  forgejo: "forgejo",
} as const;
export type VcsProviderValue = (typeof VcsProvider)[keyof typeof VcsProvider];

export interface VcsLink {
  id: string;
  item_id: string;
  ref_type: VcsRefTypeValue;
  provider: VcsProviderValue;
  title: string;
  url: string;
  status: string;
  external_id: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /** Spec 111 — latest CI run for this ref ("" = never reported). */
  ci_state: string;
  ci_url: string;
}

export interface VcsLinkCreate {
  ref_type: VcsRefTypeValue;
  provider?: VcsProviderValue;
  title: string;
  url: string;
  status?: string;
  external_id?: string;
}

/** Forgejo/Gitea hosts and repositories as rows (spec 111). */
export type ForgejoConnection = {
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

export type ForgejoRepo = {
  id: string;
  connection_id: string;
  full_name: string;
  project_id: string | null;
  default_branch: string;
  last_backfill_at: string | null;
  created_at: string;
};

export type ForgejoConnectionTest = { ok: boolean; version: string; detail: string };

export type ForgejoBackfillReport = {
  branches: number;
  pull_requests: number;
  commits: number;
  linked: number;
  unknown_keys: string[];
};
