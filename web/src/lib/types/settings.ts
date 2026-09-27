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
  /** Null for a secret: its value never leaves the server (RADD-1454). */
  value: unknown;
  /** RADD-1454, secrets only: whether a non-empty value is in effect (here, inherited or from
   * the environment). Null on every other row. */
  set?: boolean | null;
  set_here: boolean; // overridden at THIS scope (vs inherited)
  default: unknown; // the env/config fallback; null for a secret
  /** Enumerated settings only: the accepted values — render a select. */
  choices?: string[] | null;
  /** Sealed at rest and never read back (RADD-1424/RADD-1454): the editor shows `set` and takes
   * a replacement; an empty write keeps the stored value, Clear removes the override. */
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
 * Placing a setting by the surface it declares (RADD-930). A `section` is a dotted path: its ROOT
 * names the page, deeper parts a card within it; `inSection` matches a section and everything
 * under it. A General page renders the REMAINDER (rows no page `homed`), so a row lands somewhere.
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
