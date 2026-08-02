/** Instance status, scoped settings cascade, and instance roles (specs 50/67/85). */
/** Non-secret deploy status for the instance settings surface (spec 50). */
export interface InstanceStatus {
  sso_enabled: boolean;
  ldap_enabled: boolean;
  /** Spec 84: a directory service account is configured — gates the AD
   * group/user import + team-sync affordances. */
  ldap_bind_account: boolean;
  smtp_configured: boolean;
  mfa_available: boolean;
  ai_provider: string;
  attachment_storage: string;
  workers_enabled: boolean;
  connectors: Record<string, boolean>;
}

/** Two-scope settings (spec 67): instance defaults, project overrides. */
export const SettingScope = {
  instance: "instance",
  project: "project",
} as const;
export type SettingScopeValue = (typeof SettingScope)[keyof typeof SettingScope];

/** One row of GET /scoped-settings — a cascaded scalar's effective value (spec 50). */
export interface ScopedSetting {
  key: string;
  type: string;
  label: string;
  description: string;
  value: unknown;
  set_here: boolean; // overridden at THIS scope (vs inherited)
  default: unknown; // the env/config fallback
  /** Enumerated settings only: the accepted values — render a select. */
  choices?: string[] | null;
}

/** Registered scalar setting keys the SPA reads by name (mirror of the backend
 * `SettingKey` — only the ones with a client-side gate are listed). */
export const SettingKey = {
  estimationPoints: "estimation_points",
  // Directory settings (spec 85) — instance-only; edited on Settings → Directory.
  ldapUserSyncBase: "ldap_user_sync_base",
  ldapUserSyncEnabled: "ldap_user_sync_enabled",
  ldapExcludeDisabled: "ldap_exclude_disabled",
  ldapUserSyncDeactivateMissing: "ldap_user_sync_deactivate_missing",
  ldapGroupSearchBase: "ldap_group_search_base",
  // AI feature toggles (spec 101) — instance-only; edited on Settings → AI.
  aiEditorActions: "ai_editor_actions",
  aiSemanticSearch: "ai_semantic_search",
  aiStorageRouting: "ai_storage_routing",
  aiSummarize: "ai_summarize",
  aiNlSlq: "ai_nl_slq",
  aiSimilarRerank: "ai_similar_rerank",
  aiStreamResponses: "ai_stream_responses",
} as const;
export type SettingKeyValue = (typeof SettingKey)[keyof typeof SettingKey];

/** The directory keys live on the Directory page (spec 85) — the General tab's
 * instance editor filters them out so they aren't scattered across two tabs. */
export const DIRECTORY_USER_SYNC_KEYS: readonly string[] = [
  SettingKey.ldapUserSyncBase,
  // Whether leavers are imported at all — the setting that decides how much of a
  // real directory lands in Radd (one live instance: 2057 disabled vs 1031 active).
  SettingKey.ldapExcludeDisabled,
  SettingKey.ldapUserSyncEnabled,
  SettingKey.ldapUserSyncDeactivateMissing,
];
export const DIRECTORY_GROUP_KEYS: readonly string[] = [SettingKey.ldapGroupSearchBase];
export const DIRECTORY_SETTING_KEYS: readonly string[] = [
  ...DIRECTORY_USER_SYNC_KEYS,
  ...DIRECTORY_GROUP_KEYS,
];

/** The AI feature toggles live on Settings → AI (spec 101) — the General tab's
 * instance editor filters them out, same registry as the directory keys. */
export const AI_FEATURE_SETTING_KEYS: readonly string[] = [
  SettingKey.aiEditorActions,
  SettingKey.aiSemanticSearch,
  SettingKey.aiStorageRouting,
  SettingKey.aiSummarize,
  SettingKey.aiNlSlq,
  SettingKey.aiSimilarRerank,
  SettingKey.aiStreamResponses,
];

/** GET /scoped-settings/resolve — one key's cascade-resolved value (spec 70):
 * the project override if any, else the instance override, else the default. */
export interface ResolvedSetting {
  key: string;
  value: unknown;
}

export const InstanceRole = {
  admin: "admin",
  member: "member",
} as const;
export type InstanceRoleValue = (typeof InstanceRole)[keyof typeof InstanceRole];
