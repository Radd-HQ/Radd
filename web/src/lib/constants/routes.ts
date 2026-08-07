/** Route path segments + settings sections — literal types matter: TanStack Router's typed `to` union is built from them. */

/** Route path segments — literal types matter: TanStack Router's typed `to` union
 * is built from them (a widened `string` path would untype the whole subtree). */
const PROJECT_SEGMENT = "/p/$projectKey";
const VIEW_SEGMENT = "/v/$viewId";
const CYCLE_SEGMENT = "/cycles/$cycleId";
const SETTINGS_SEGMENT = "/settings";
/** Per-project settings live UNDER the project (spec 50), gated by that project's perms. */
const PROJECT_SETTINGS_SEGMENT = `${PROJECT_SEGMENT}/settings`;

/** Settings sections — relative child segments under /settings (router registration). */
export const SettingsSection = {
  profile: "profile",
  // Server/deploy status (spec 50; status-only since spec 67) — admin only.
  instance: "instance",
  // Instance-scope product defaults (spec 67 two-scope cascade) — admin only.
  general: "general",
  fields: "fields",
  // Issue link types (spec 91) — admin only.
  linkTypes: "link-types",
  labels: "labels",
  cycles: "cycles",
  teams: "teams",
  // Directory-mirrored groups (RADD-833) — read-only, admin-facing.
  groups: "groups",
  // The people page (spec 84; role ladder = instance_role since spec 86) — admins.
  users: "users",
  // Consolidated Directory/LDAP settings (spec 85) — admin only.
  directory: "directory",
  // Jira import wizard (spec 90) — admin only.
  jiraImport: "jira-import",
  roles: "roles",
  tokens: "tokens",
  automations: "automations",
  // Per-project time-logging enablement moved under the project (spec 50);
  // this global section keeps the shared work categories.
  timelogging: "timelogging",
  audit: "audit",
  canned: "canned",
  forgejo: "forgejo",
  serviceAccounts: "service-accounts",
  pages: "pages",
  // Plugin manager (spec 93 / A4) — install/enable/disable non-core plugins. Admin.
  plugins: "plugins",
  // Backups (spec 99) — schedules, artifacts, restore. Instance admin only.
  backups: "backups",
  // AI provider registry + roles + feature toggles + presets (spec 101) — admin only.
  ai: "ai",
  // Attachment storage hosts + delivery (spec 102) — admin only.
  storage: "storage",
  // Mail sources/senders + the routing chain (RADD-958) — admin only.
  email: "email",
  // SSO provider registry + signup domain allowlists (spec 110) — admin only.
  signIn: "sign-in",
  // Operator monitoring: DB health, counts, worker lag — admin only.
  monitoring: "monitoring",
  // Per-team public holidays (People group) — admin-managed.
  holidays: "holidays",
} as const;
export type SettingsSectionValue = (typeof SettingsSection)[keyof typeof SettingsSection];

/**
 * Project-settings sections — relative child segments under
 * `/p/$projectKey/settings` (spec 50). Each is gated by the corresponding
 * per-project manage permission in `ProjectSettingsLayout`.
 */
export const ProjectSettingsSection = {
  general: "general",
  access: "access",
  workflow: "workflow",
  types: "types",
  screens: "screens",
  releases: "releases",
  forms: "forms",
  timelogging: "timelogging",
  // SLA policies are project-level since spec 67.
  sla: "sla",
} as const;
export type ProjectSettingsSectionValue =
  (typeof ProjectSettingsSection)[keyof typeof ProjectSettingsSection];

/** Route paths — the single source of truth for navigation targets. */
export const RoutePath = {
  /** "My Work" personal dashboard — the landing page (spec 32). */
  home: "/",
  /** The projects index (was the landing page pre-spec-32). */
  projects: "/projects",
  login: "/login",
  project: PROJECT_SEGMENT,
  /** LEGACY roadmap path (spec 19; redirects to the project's first
   * roadmap-type view since spec 79 — roadmaps are saved views). */
  roadmap: `${PROJECT_SEGMENT}/roadmap`,
  /** Reporting dashboards for a project (spec 19). */
  projectReports: `${PROJECT_SEGMENT}/reports`,
  /** Server-wide reporting (velocity across cycles) (spec 19). */
  reports: "/reports",
  /** The timesheet — day/week/month time reports (spec 22). */
  timesheet: "/timesheet",
  /** Personal notification inbox (spec 26). */
  inbox: "/inbox",
  /** Requester portal (spec 73): the intake-form directory — every signed-in user. */
  portal: "/portal",
  /** Portal submit page for one eligible form (spec 73). */
  portalForm: "/portal/forms/$formId",
  /** Canonical, key-addressed issue URL (Jira-style): `/issues/TD-1234`. */
  issue: "/issues/$itemKey",
  /** Saved view scoped to a project (spec 09). */
  projectView: `${PROJECT_SEGMENT}${VIEW_SEGMENT}`,
  /** All-projects saved view (project_id null). */
  allProjectsView: VIEW_SEGMENT,
  /** A cycle's items page (spec 18) — cycles span projects. */
  cycle: CYCLE_SEGMENT,
  /** Public-shaped intake form submit page (spec 20) — members, behind the auth gate. */
  formSubmit: `${PROJECT_SEGMENT}/forms/$formId`,
  /** Truly PUBLIC tokened form submit page (spec 62) — root-level, outside the auth gate. */
  /** PUBLIC tokened CSAT rating page (spec 65) — root-level, outside the auth gate. */
  publicCsat: "/public/csat/$token",
  settings: SETTINGS_SEGMENT,
  /**
   * Per-project settings (spec 50) — nested under the project so the sub-nav is
   * gated by THAT project's permissions and the project comes from the URL.
   */
  projectSettings: PROJECT_SETTINGS_SEGMENT,
  projectSettingsGeneral: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.general}`,
  /** Project access: direct members + team attachments (`project.manage`). */
  projectSettingsAccess: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.access}`,
  /** Workflow states for the project (`state.manage`). */
  projectSettingsWorkflow: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.workflow}`,
  projectSettingsTypes: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.types}`,
  projectSettingsScreens: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.screens}`,
  /** Releases/versions for the project (`release.manage`). */
  projectSettingsReleases: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.releases}`,
  /** Intake forms for the project (`form.manage`). */
  projectSettingsForms: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.forms}`,
  /** Per-project time-logging enablement (`project.manage`). */
  projectSettingsTimelogging: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.timelogging}`,
  /** SLA policies for the project (spec 67; `sla.manage` to edit). */
  projectSettingsSla: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.sla}`,
  /** Personal profile: avatar, timezone, API tokens (spec 34). */
  settingsProfile: `${SETTINGS_SEGMENT}/${SettingsSection.profile}`,
  /** Server/deploy status, read-only (spec 50; status-only since spec 67, admin). */
  settingsInstance: `${SETTINGS_SEGMENT}/${SettingsSection.instance}`,
  /** Instance-scope product defaults — projects override (spec 67, admin). */
  settingsGeneral: `${SETTINGS_SEGMENT}/${SettingsSection.general}`,
  settingsFields: `${SETTINGS_SEGMENT}/${SettingsSection.fields}`,
  settingsLinkTypes: `${SETTINGS_SEGMENT}/${SettingsSection.linkTypes}`,
  settingsLabels: `${SETTINGS_SEGMENT}/${SettingsSection.labels}`,
  settingsCycles: `${SETTINGS_SEGMENT}/${SettingsSection.cycles}`,
  settingsGroups: `${SETTINGS_SEGMENT}/${SettingsSection.groups}`,
  settingsTeams: `${SETTINGS_SEGMENT}/${SettingsSection.teams}`,
  /** THE people page (spec 84): accounts + the instance_role ladder (spec 86),
   * dedupe/merge. */
  settingsUsers: `${SETTINGS_SEGMENT}/${SettingsSection.users}`,
  /** Consolidated Directory/LDAP settings (spec 85): user sync + group import/links. */
  settingsDirectory: `${SETTINGS_SEGMENT}/${SettingsSection.directory}`,
  settingsJiraImport: `${SETTINGS_SEGMENT}/${SettingsSection.jiraImport}`,
  settingsRoles: `${SETTINGS_SEGMENT}/${SettingsSection.roles}`,
  settingsTokens: `${SETTINGS_SEGMENT}/${SettingsSection.tokens}`,
  /** Automation rules admin (spec 20, global, `automation.manage`). */
  settingsAutomations: `${SETTINGS_SEGMENT}/${SettingsSection.automations}`,
  /** Work-categories admin (spec 22/50, global manage) — the shared category list. */
  settingsTimelogging: `${SETTINGS_SEGMENT}/${SettingsSection.timelogging}`,
  /** Audit log (admin): every attributable change across the server. */
  settingsAudit: `${SETTINGS_SEGMENT}/${SettingsSection.audit}`,
  settingsBackups: `${SETTINGS_SEGMENT}/${SettingsSection.backups}`,
  /** AI providers, model roles, feature toggles, preset prompts (spec 101, admin). */
  settingsAi: `${SETTINGS_SEGMENT}/${SettingsSection.ai}`,
  /** Attachment storage hosts + delivery modes (spec 102, admin). */
  settingsStorage: `${SETTINGS_SEGMENT}/${SettingsSection.storage}`,
  /** Mail sources, senders and routing rules (RADD-958, admin). */
  settingsEmail: `${SETTINGS_SEGMENT}/${SettingsSection.email}`,
  /** SSO providers + per-provider signup domain allowlists (spec 110, admin). */
  settingsSignIn: `${SETTINGS_SEGMENT}/${SettingsSection.signIn}`,
  settingsMonitoring: `${SETTINGS_SEGMENT}/${SettingsSection.monitoring}`,
  settingsHolidays: `${SETTINGS_SEGMENT}/${SettingsSection.holidays}`,
  /** Plugin manager (spec 93 / A4, admin): install/enable/disable plugins. */
  settingsPlugins: `${SETTINGS_SEGMENT}/${SettingsSection.plugins}`,
  /** Canned responses admin (spec 30, global manage). */
  settingsCanned: `${SETTINGS_SEGMENT}/${SettingsSection.canned}`,
  settingsForgejo: `${SETTINGS_SEGMENT}/${SettingsSection.forgejo}`,
  settingsServiceAccounts: `${SETTINGS_SEGMENT}/${SettingsSection.serviceAccounts}`,
  /** Pages (spec 43; RADD-702): spaces index, a space's tree, and the canonical
   *  page URL — `/pages/<space>/<page>`. Either segment may carry a SLUG or an
   *  id: links built from an id still resolve, and the page view rewrites the
   *  URL to the canonical slug form, so no link ever shared can rot. */
  pages: "/pages",
  pageSpace: "/pages/$spaceSlug",
  page: "/pages/$spaceSlug/$pageSlug",
  /** RADD-733: the print view — a TOP-LEVEL route, outside the app layout,
   *  because the layout is exactly what must not be in the output. */
  pagePrint: "/pages/$spaceSlug/$pageSlug/print",
  /** Page spaces admin (spec 43, doc.manage). */
  settingsPages: `${SETTINGS_SEGMENT}/${SettingsSection.pages}`,
  /** PUBLIC pages (spec 74) — root-level, outside the auth gate. */
  publicPages: "/public-pages",
  publicPageSpace: "/public-pages/$spaceSlug",
  publicPage: "/public-pages/$spaceSlug/$pageSlug",
  // Kept until V1: the instance is public and old /kb links live in the wild (RADD-896).
  legacyKb: "/kb",
  legacyKbSpace: "/kb/$spaceSlug",
  legacyKbPage: "/kb/$spaceSlug/$pageSlug",
  /** A composable dashboard's widget grid (spec 75). */
  dashboard: "/dashboards/$dashboardId",
} as const;
export type RoutePathValue = (typeof RoutePath)[keyof typeof RoutePath];
