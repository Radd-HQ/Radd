/** Route path segments + settings sections. Literal types matter: TanStack Router's typed `to`
 *  union is built from them (a widened `string` path would untype the whole subtree). */
const PROJECT_SEGMENT = "/p/$projectKey";
const VIEW_SEGMENT = "/v/$viewId";
const CYCLE_SEGMENT = "/cycles/$cycleId";
const SETTINGS_SEGMENT = "/settings";
/** Per-project settings live UNDER the project (spec 50), gated by that project's perms. */
const PROJECT_SETTINGS_SEGMENT = `${PROJECT_SEGMENT}/settings`;

/** Settings sections — relative child segments under /settings (router registration). */
export const SettingsSection = {
  profile: "profile",
  instance: "instance",
  general: "general",
  fields: "fields",
  linkTypes: "link-types",
  labels: "labels",
  cycles: "cycles",
  teams: "teams",
  users: "users",
  roles: "roles",
  tokens: "tokens",
  timelogging: "timelogging",
  canned: "canned",
  serviceAccounts: "service-accounts",
  pages: "pages",
  plugins: "plugins",
  backups: "backups",
  storage: "storage",
  signIn: "sign-in",
  webhooks: "webhooks",
  // Folded into Time logging (RADD-932); the path redirects there.
  holidays: "holidays",
  notifications: "notifications",
} as const;

/** Project-settings sections — child segments under `/p/$projectKey/settings`. */
export const ProjectSettingsSection = {
  general: "general",
  access: "access",
  workflow: "workflow",
  types: "types",
  screens: "screens",
  releases: "releases",
  forms: "forms",
  timelogging: "timelogging",
} as const;

/** Route paths — the single source of truth for navigation targets. */
export const RoutePath = {
  /** "My Work" — the landing page. */
  home: "/",
  projects: "/projects",
  login: "/login",
  project: PROJECT_SEGMENT,
  /** LEGACY roadmap path (spec 19; redirects to the project's first
   * roadmap-type view since spec 79 — roadmaps are saved views). */
  roadmap: `${PROJECT_SEGMENT}/roadmap`,
  projectReports: `${PROJECT_SEGMENT}/reports`,
  /** A project's releases and what shipped in each (RADD-1290) — a project page, not a setting. */
  projectReleases: `${PROJECT_SEGMENT}/releases`,
  reports: "/reports",
  timesheet: "/timesheet",
  inbox: "/inbox",
  starred: "/starred",
  portal: "/portal",
  portalForm: "/portal/forms/$formId",
  issue: "/issues/$itemKey",
  /** RADD-1493: an epic as an all-projects board (a synthetic view — no saved row). */
  epicBoard: "/e/$itemKey/board",
  projectView: `${PROJECT_SEGMENT}${VIEW_SEGMENT}`,
  /** A saved view with no project (project_id null). */
  allProjectsView: VIEW_SEGMENT,
  cycle: CYCLE_SEGMENT,
  /** Intake form submit page — members only, behind the sign-in gate. */
  formSubmit: `${PROJECT_SEGMENT}/forms/$formId`,
  /** PUBLIC pages (RADD-1401) — root-level, outside the shell and the sign-in gate: a plugin's
   *  `public.page` contribution answers the path (a tokened link from an email). */
  publicPage: "/public/$",
  settings: SETTINGS_SEGMENT,
  projectSettings: PROJECT_SETTINGS_SEGMENT,
  projectSettingsGeneral: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.general}`,
  projectSettingsAccess: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.access}`,
  projectSettingsWorkflow: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.workflow}`,
  projectSettingsTypes: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.types}`,
  projectSettingsScreens: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.screens}`,
  projectSettingsForms: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.forms}`,
  projectSettingsTimelogging: `${PROJECT_SETTINGS_SEGMENT}/${ProjectSettingsSection.timelogging}`,
  settingsProfile: `${SETTINGS_SEGMENT}/${SettingsSection.profile}`,
  settingsInstance: `${SETTINGS_SEGMENT}/${SettingsSection.instance}`,
  settingsGeneral: `${SETTINGS_SEGMENT}/${SettingsSection.general}`,
  settingsFields: `${SETTINGS_SEGMENT}/${SettingsSection.fields}`,
  settingsLinkTypes: `${SETTINGS_SEGMENT}/${SettingsSection.linkTypes}`,
  settingsLabels: `${SETTINGS_SEGMENT}/${SettingsSection.labels}`,
  settingsCycles: `${SETTINGS_SEGMENT}/${SettingsSection.cycles}`,
  settingsTeams: `${SETTINGS_SEGMENT}/${SettingsSection.teams}`,
  settingsUsers: `${SETTINGS_SEGMENT}/${SettingsSection.users}`,
  settingsRoles: `${SETTINGS_SEGMENT}/${SettingsSection.roles}`,
  settingsTokens: `${SETTINGS_SEGMENT}/${SettingsSection.tokens}`,
  settingsNotifications: `${SETTINGS_SEGMENT}/${SettingsSection.notifications}`,
  settingsTimelogging: `${SETTINGS_SEGMENT}/${SettingsSection.timelogging}`,
  settingsBackups: `${SETTINGS_SEGMENT}/${SettingsSection.backups}`,
  settingsStorage: `${SETTINGS_SEGMENT}/${SettingsSection.storage}`,
  settingsSignIn: `${SETTINGS_SEGMENT}/${SettingsSection.signIn}`,
  settingsWebhooks: `${SETTINGS_SEGMENT}/${SettingsSection.webhooks}`,
  settingsPlugins: `${SETTINGS_SEGMENT}/${SettingsSection.plugins}`,
  settingsCanned: `${SETTINGS_SEGMENT}/${SettingsSection.canned}`,
  settingsServiceAccounts: `${SETTINGS_SEGMENT}/${SettingsSection.serviceAccounts}`,
  /** The wiki's own addresses are the pages plugin's `PageRoute` (RADD-1392). Page spaces admin
   *  (spec 43) is its settings page; the host keeps the nav row, which asks about ANY space. */
  settingsPages: `${SETTINGS_SEGMENT}/${SettingsSection.pages}`,
  // Kept until V1: the instance is public and old /kb links live in the wild (RADD-896).
  legacyKb: "/kb",
  legacyKbSpace: "/kb/$spaceSlug",
  legacyKbPage: "/kb/$spaceSlug/$pageSlug",
  dashboard: "/dashboards/$dashboardId",
} as const;
