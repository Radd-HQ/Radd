/** Instance status, scoped settings cascade, and instance roles (specs 50/67/85). */
/** Non-secret deploy status for the instance settings surface (spec 50). */
export interface InstanceStatus {
  sso_enabled: boolean;
  ldap_enabled: boolean;
  /** Spec 84: a directory service account is configured — gates the AD
   * group/user import + team-sync affordances. */
  ldap_bind_account: boolean;
  smtp_configured: boolean;
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
  /** RADD-846: render a masked input (the value itself is admin-readable). */
  secret?: boolean;
  /** RADD-930: the settings surface this key belongs on, declared by the owning
   * plugin. "" (or absent) = the scope's General page. */
  section?: string;
}

/**
 * Placing a setting by the surface it declares (RADD-930).
 *
 * A `section` is a dotted path: its ROOT names the page, and anything deeper
 * names a card within it (`directory.connection` vs `directory.groups`), so one
 * page can lay its own rows out in groups without a second vocabulary.
 *
 * `inSection` matches a section and everything under it. `withoutSections` is
 * what a General page renders: the REMAINDER — rows with no section, plus rows
 * whose root names a surface that doesn't exist at this scope (the release
 * states have a Releases tab per project but not per instance) or at all.
 * Computing General by subtraction rather than giving it a section name of its
 * own is what makes a departed or misspelt section degrade to "appears on
 * General" instead of "silently unreachable".
 */
const sectionRoot = (row: ScopedSetting) => (row.section ?? "").split(".")[0];

export function inSection(rows: readonly ScopedSetting[], section: string): ScopedSetting[] {
  return rows.filter((row) => {
    const own = row.section ?? "";
    return own === section || own.startsWith(`${section}.`);
  });
}

export function withoutSections(
  rows: readonly ScopedSetting[],
  homed: readonly string[],
): ScopedSetting[] {
  const claimed = new Set(homed);
  return rows.filter((row) => !claimed.has(sectionRoot(row)));
}

/** Section roots that have their own surface at each scope — everything else
 *  falls back to that scope's General page (see `withoutSections`). */
/** RADD-1045: "email" is claimed by Settings → Email's `AckTemplatePanel`,
 *  which reads its own row directly rather than through `ScopedSettingsEditor`
 *  — but the section still has to be listed here, or the General page (which
 *  computes its rows by SUBTRACTION) would render a second, generic editor
 *  for the same key. */
export const INSTANCE_HOMED_SECTIONS: readonly string[] = [
  "directory",
  "ai",
  "timelogging",
  "email",
  "signin", // RADD-1279: require_mfa lives on Settings → Sign-in
];
export const PROJECT_HOMED_SECTIONS: readonly string[] = [
  "timelogging",
  "sla",
  "workflow",
];

/** Registered scalar setting keys the SPA reads by name (mirror of the backend
 * `SettingKey` — only the ones with a client-side gate are listed). */
export const SettingKey = {
  estimationPoints: "estimation_points",
  // Directory settings (spec 85 + RADD-846) — instance-only; Settings → Directory.
  ldapUrl: "ldap_url",
  ldapUserDomain: "ldap_user_domain",
  ldapBindDn: "ldap_bind_dn",
  ldapBindPassword: "ldap_bind_password",
  ldapAdminGroups: "ldap_admin_groups",
  ldapGroupSyncSeconds: "ldap_group_sync_seconds",
  ldapUserSyncBase: "ldap_user_sync_base",
  ldapUserSyncEnabled: "ldap_user_sync_enabled",
  ldapExcludeDisabled: "ldap_exclude_disabled",
  ldapUserSyncDeactivateMissing: "ldap_user_sync_deactivate_missing",
  ldapGroupSearchBase: "ldap_group_search_base",
  // AI feature toggles (spec 101) — instance-only; edited on Settings → AI.
  aiEditorActions: "ai_editor_actions",
  aiSemanticSearch: "ai_semantic_search",
  aiStorageRouting: "ai_storage_routing",
  aiMailRouting: "ai_mail_routing",
  aiSummarize: "ai_summarize",
  aiNlSlq: "ai_nl_slq",
  aiSimilarRerank: "ai_similar_rerank",
  aiStreamResponses: "ai_stream_responses",
} as const;
export type SettingKeyValue = (typeof SettingKey)[keyof typeof SettingKey];

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
