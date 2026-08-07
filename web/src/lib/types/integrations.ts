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


// ---------------------------------------------------------------------------
// Mail configuration (RADD-958) — Settings → Email
// ---------------------------------------------------------------------------

export const MailSourceKind = { webhook: "webhook", imap: "imap" } as const;
export type MailSourceKindValue = (typeof MailSourceKind)[keyof typeof MailSourceKind];

export const MailRuleType = {
  recipient: "recipient",
  sender: "sender",
  subject: "subject",
  llm: "llm",
} as const;
export type MailRuleTypeValue = (typeof MailRuleType)[keyof typeof MailRuleType];

/** Where mail comes IN. `has_secret` never carries the value — secrets are
 *  write-only here, the same rule Storage/Sign-in/AI follow. */
export interface MailSource {
  id: string;
  name: string;
  kind: MailSourceKindValue;
  enabled: boolean;
  address: string;
  host: string;
  port: number;
  username: string;
  folder: string;
  default_project_id: string | null;
  has_secret: boolean;
  rule_count: number;
}

/** Where mail goes OUT. */
export interface MailSender {
  id: string;
  name: string;
  kind: "smtp";
  enabled: boolean;
  is_default: boolean;
  from_address: string;
  reply_to: string;
  host: string;
  port: number;
  username: string;
  starttls: boolean;
  has_secret: boolean;
}

/** One step of a source's ordered chain. First enabled match wins. */
export interface MailRule {
  id: string;
  source_id: string;
  name: string;
  rule_type: MailRuleTypeValue;
  enabled: boolean;
  position: number;
  config: Record<string, unknown>;
  project_id: string | null;
}

/** A test send reports the Message-ID the RELAY used — the value threading
 *  depends on (RADD-955), so showing it makes "did that work" verifiable. */
export interface MailTestResult {
  ok: boolean;
  message_id: string;
  error: string;
}

/** The dry run: where would a message like this land, and what decided. */
export interface RoutingPreviewResult {
  project_id: string | null;
  project_key: string;
  matched_rule_id: string | null;
  matched_rule_name: string;
  reason: string;
}
