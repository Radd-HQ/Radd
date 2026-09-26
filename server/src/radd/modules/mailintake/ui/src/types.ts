/** mailintake wire types; mirrors `mailintake/config_schemas.py`. */

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

/** One `GET /mail/kinds` entry. `preset` = the connection is answered, so the form HIDES host/port/TLS
 *  rather than pre-filling them (an edited copy would outlive the preset). */
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
  /** "Send replies from"; null = the default sender. */
  sender_id: string | null;
  /** Authentication-Results authserv-id whose SPF/DKIM/DMARC verdict this source trusts; null = trust
   *  nothing. A message failing or lacking it is attributed to SYSTEM, not the account it may forge. */
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

/** What one rule did on the sample. `errored` separates a crashed rule from a declining one;
 *  `disabled`/`not_reached` make an empty row mean something. A Record over this forces STATUS_STYLE to cover all. */
export const MailRuleStatus = {
  matched: "matched",
  declined: "declined",
  errored: "errored",
  disabled: "disabled",
  not_reached: "not_reached",
} as const;
export type MailRuleStatusValue = (typeof MailRuleStatus)[keyof typeof MailRuleStatus];

/** Mirrors `mailintake/types.py` NO_MATCH_ANSWER: appended at ask time, never stored, so the
 *  editor must SHOW it. A wire constant — rewording the Python side leaves this stale. */
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
