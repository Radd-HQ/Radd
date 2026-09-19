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
  /** RADD-1258: the work category a worklog mirrored from this repository's
   *  MRs/PRs carries; null = the instance's Development. */
  time_category_id: string | null;
  created_at: string;
};

export type ForgejoConnectionTest = { ok: boolean; version: string; detail: string };

/** GitHub hosts and repositories as rows (RADD-1129) — same wire shape as Forgejo. */
export type GithubConnection = ForgejoConnection;
export type GithubRepo = ForgejoRepo;
export type GithubConnectionTest = ForgejoConnectionTest;

/** GitLab hosts and projects as rows (RADD-1253) — same wire shape again;
 *  `full_name` is GitLab's `path_with_namespace`. */
export type GitlabConnection = ForgejoConnection;
export type GitlabRepo = ForgejoRepo;
export type GitlabConnectionTest = ForgejoConnectionTest;

export type ForgejoBackfillReport = {
  branches: number;
  pull_requests: number;
  commits: number;
  linked: number;
  unknown_keys: string[];
};

/** RADD-1258 — how a provider account was tied to a Radd user. */
export const VcsMatchedBy = { email: "email", manual: "manual" } as const;
export type VcsMatchedByValue = (typeof VcsMatchedBy)[keyof typeof VcsMatchedBy];

/** One row of a connection's identity map (`GET /vcs/{provider}/connections/{id}/identities`). */
export interface VcsUserLink {
  id: string;
  provider: VcsProviderValue;
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
  last_seen_at: string | null;
}

export interface VcsUserLinkSet {
  external_username: string;
  user_id: string;
}

export interface VcsReplayResult {
  replayed: number;
}


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
 * identically — and a broken rule reads as an inapplicable one.
 *
 * `disabled` and `not_reached` (RADD-994) are what make an EMPTY row meaningful:
 * a switched-off rule, a rule below the winner and a deleted rule used to render
 * as the same absence, so the trace answered "why didn't my rule fire" with
 * silence. Adding them here is what forces `STATUS_STYLE` to grow chrome for
 * them — a `Record` over this const cannot compile with a status missing. */
export const MailRuleStatus = {
  matched: "matched",
  declined: "declined",
  errored: "errored",
  disabled: "disabled",
  not_reached: "not_reached",
} as const;
export type MailRuleStatusValue = (typeof MailRuleStatus)[keyof typeof MailRuleStatus];

/** The extra answer every AI routing rule offers the model on top of its own
 * categories — mirrored from `mailintake/types.py`'s `NO_MATCH_ANSWER` (RADD-989).
 * It is appended at ask time and never stored as an answer row, which is exactly
 * why the editor has to STATE it (RADD-994): an admin who cannot see it either
 * writes a prompt that fights it ("answer only Engineering or IT") or adds their
 * own duplicate "Other → DESK". A wire constant with no compiler behind it — if
 * the Python side is reworded, this line is what goes stale. */
export const MAIL_NO_MATCH_ANSWER = "None of these";

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
  /** The whole chain, in order: consulted, skipped (disabled) or never reached. */
  outcomes: RoutingRuleOutcome[];
}
