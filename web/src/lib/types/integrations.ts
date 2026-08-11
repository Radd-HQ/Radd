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
// Mail configuration (RADD-958/969) — Settings → Email
// ---------------------------------------------------------------------------

/** How mail reaches Radd. `google`/`outlook` are PRESETS over IMAP, not separate
 *  transports: the row leaves the connection blank and the kind answers it. */
export const MailSourceKind = {
  webhook: "webhook",
  imap: "imap",
  google: "google",
  outlook: "outlook",
} as const;
export type MailSourceKindValue = (typeof MailSourceKind)[keyof typeof MailSourceKind];

/** Where mail goes out. `google`/`outlook` are SMTP with the connection answered. */
export const MailSenderKind = {
  smtp: "smtp",
  google: "google",
  outlook: "outlook",
} as const;
export type MailSenderKindValue = (typeof MailSenderKind)[keyof typeof MailSenderKind];

/**
 * One entry of `GET /mail/kinds` (RADD-969) — what the add form prefills itself
 * with, per the spec-110 `SsoKindInfo` pattern.
 *
 * `preset` is the flag the form branches on: true means the connection is
 * answered, so host/port/TLS are HIDDEN rather than shown pre-filled — a field
 * showing `imap.gmail.com` invites an edit, and the edited value would then
 * outlive the preset it was copied from.
 */
export interface MailKindInfo {
  /** A `MailSourceKindValue` under `sources`, a `MailSenderKindValue` under `senders`. */
  kind: string;
  name: string;
  summary: string;
  host: string;
  port: number;
  starttls: boolean;
  guidance: string;
  help_url: string;
  preset: boolean;
}

/** Both halves in one response — the two dialogs share a query. */
export interface MailKinds {
  sources: MailKindInfo[];
  senders: MailKindInfo[];
}

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
  /** RAW, as stored — blank on a preset kind. What the EDIT FORM shows. */
  host: string;
  port: number;
  username: string;
  folder: string;
  default_project_id: string | null;
  /** "Send replies from" (RADD-979) — the sender that answers for this address.
   *  null = the default sender, which is what every source did before. */
  sender_id: string | null;
  /** The `Authentication-Results` authserv-id whose SPF/DKIM/DMARC verdict this
   *  source trusts (RADD-1032). null/blank = trust nothing — the default, so
   *  `From:` is taken at face value exactly as before. Set it and a message
   *  failing (or lacking) that verdict is attributed to SYSTEM, not the account
   *  it may have forged. */
  trusted_authserv_id: string | null;
  has_secret: boolean;
  rule_count: number;
  /** What the poller will actually use: the row value or the kind's preset
   *  (RADD-969). What the LIST shows. */
  resolved_host: string;
  resolved_port: number;
  resolved_username: string;
}

/** Where mail goes OUT. */
export interface MailSender {
  id: string;
  name: string;
  kind: MailSenderKindValue;
  enabled: boolean;
  is_default: boolean;
  from_address: string;
  reply_to: string;
  /** RAW, as stored — blank on a preset kind. */
  host: string;
  port: number;
  username: string;
  starttls: boolean;
  has_secret: boolean;
  /** What the relay will actually be dialled with (RADD-969). */
  resolved_host: string;
  resolved_port: number;
  resolved_username: string;
  resolved_starttls: boolean;
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

/** What one rule did on the sample message (RADD-989). `errored` is the reason
 * this exists: a rule that CRASHED and one that simply declined both let the
 * chain fall to the source default, so a destination alone describes them
 * identically — and a broken rule reads as an inapplicable one. */
export const MailRuleStatus = {
  matched: "matched",
  declined: "declined",
  errored: "errored",
} as const;
export type MailRuleStatusValue = (typeof MailRuleStatus)[keyof typeof MailRuleStatus];

export interface RoutingRuleOutcome {
  rule_id: string | null;
  rule_name: string;
  status: MailRuleStatusValue;
  detail: string;
}

/** The dry run: where would a message like this land, and what decided. */
export interface RoutingPreviewResult {
  project_id: string | null;
  project_key: string;
  matched_rule_id: string | null;
  matched_rule_name: string;
  reason: string;
  /** Every rule consulted, in chain order, up to and including the match. */
  outcomes: RoutingRuleOutcome[];
}
