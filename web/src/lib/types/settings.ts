/** Instance status, scoped settings cascade, and instance roles (specs 50/67/85). */

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
  /** RADD-1368: prose (a mail body) — the editor renders a textarea. */
  multiline?: boolean;
  /** RADD-930: the settings surface this key belongs on, declared by the owning
   * plugin. "" (or absent) = the scope's General page. */
  section?: string;
  /** RADD-1390: the owning plugin renders this row on a page of its own at THIS scope, so the
   * scope's General page leaves it out. Declared by the plugin, not listed by the host. */
  homed?: boolean;
}

/**
 * Placing a setting by the surface it declares (RADD-930).
 *
 * A `section` is a dotted path: its ROOT names the page, and anything deeper names a card within
 * it (`directory.connection` vs `directory.groups`), so one page can lay its own rows out in groups
 * without a second vocabulary. `inSection` matches a section and everything under it.
 *
 * A General page renders the REMAINDER: every row whose plugin has not declared a page of its own
 * for it at this scope (`homed`, RADD-1390 — it used to be a host list of section names that every
 * plugin page had to be added to). A row nobody homes still lands on General, never nowhere.
 */
export function inSection(rows: readonly ScopedSetting[], section: string): ScopedSetting[] {
  return rows.filter((row) => {
    const own = row.section ?? "";
    return own === section || own.startsWith(`${section}.`);
  });
}

/** Registered scalar setting keys the SPA reads by name (mirror of the backend
 * `SettingKey` — only the ones with a client-side gate are listed). */
export const SettingKey = {
  estimationPoints: "estimation_points",
  // AI feature toggles (spec 101) — instance-only; edited on Settings → AI.
  aiEditorActions: "ai_editor_actions",
  aiSemanticSearch: "ai_semantic_search",
  aiStorageRouting: "ai_storage_routing",
  aiMailSignature: "ai_mail_signature",
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
