import {
  Outlet,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  redirect,
  lazyRouteComponent,
} from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";
import { parseAuditSearch, type AuditSearch } from "./lib/audit";
import { AuthStatus } from "./lib/auth";
import { ProjectSettingsSection, RoutePath, SettingsSection } from "./lib/constants";
import { authStateQuery } from "./lib/queries";
const AppLayout = lazyRouteComponent(() => import("./routes/app-layout"), "AppLayout");
import { PluginPage } from "./components/shell/PluginPage";
import { SettingsPluginPage } from "./components/shell/SettingsPluginPage";
const CyclePage = lazyRouteComponent(() => import("./routes/cycle"), "CyclePage");
const FormSubmitPage = lazyRouteComponent(() => import("./routes/form-submit"), "FormSubmitPage");
const ItemDetailPage = lazyRouteComponent(() => import("./routes/item-page"), "ItemDetailPage");
const LoginPage = lazyRouteComponent(() => import("./routes/login"), "LoginPage");
const StarredPage = lazyRouteComponent(() => import("./routes/starred"), "StarredPage");
const MyWorkPage = lazyRouteComponent(() => import("./routes/my-work"), "MyWorkPage");
const ProjectHomePage = lazyRouteComponent(() => import("./routes/project-home"), "ProjectHomePage");
const ProjectsIndexPage = lazyRouteComponent(() => import("./routes/projects-index"), "ProjectsIndexPage");
const PublicCsatPage = lazyRouteComponent(() => import("./routes/public-csat"), "PublicCsatPage");
const RoadmapPage = lazyRouteComponent(() => import("./routes/roadmap"), "RoadmapPage");
const ReportsPage = lazyRouteComponent(() => import("./routes/reports"), "ReportsPage");
const GlobalReportsPage = lazyRouteComponent(() => import("./routes/global-reports"), "GlobalReportsPage");
const TimesheetPage = lazyRouteComponent(() => import("./routes/timesheet"), "TimesheetPage");
const InboxPage = lazyRouteComponent(() => import("./routes/inbox"), "InboxPage");
const PortalPage = lazyRouteComponent(() => import("./routes/portal"), "PortalPage");
const PortalFormPage = lazyRouteComponent(() => import("./routes/portal-form"), "PortalFormPage");
const SettingsLayout = lazyRouteComponent(() => import("./routes/settings/layout"), "SettingsLayout");
const ProjectSettingsIndex = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectSettingsIndex");
const ProjectSettingsLayout = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectSettingsLayout");
const ProjectGeneralSettings = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectGeneralSettings");
const ProjectAccessSettings = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectAccessSettings");
const ProjectWorkflowSettings = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectWorkflowSettings");
const ProjectTypesSettings = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectTypesSettings");
const ProjectScreensSettings = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectScreensSettings");
const ProjectReleasesSettings = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectReleasesSettings");
const ProjectFormsSettings = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectFormsSettings");
const ProjectTimeloggingSettings = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectTimeloggingSettings");
const ProjectSlaSettings = lazyRouteComponent(() => import("./routes/project-settings/layout"), "ProjectSlaSettings");
const GeneralSettingsPage = lazyRouteComponent(() => import("./routes/settings/general"), "GeneralSettingsPage");
const AutomationsSettingsPage = lazyRouteComponent(() => import("./routes/settings/automations"), "AutomationsSettingsPage");
const CyclesSettingsPage = lazyRouteComponent(() => import("./routes/settings/cycles"), "CyclesSettingsPage");
const FieldsSettingsPage = lazyRouteComponent(() => import("./routes/settings/fields"), "FieldsSettingsPage");
const LinkTypesSettingsPage = lazyRouteComponent(() => import("./routes/settings/link-types"), "LinkTypesSettingsPage");
const LabelsSettingsPage = lazyRouteComponent(() => import("./routes/settings/labels"), "LabelsSettingsPage");
const UsersSettingsPage = lazyRouteComponent(() => import("./routes/settings/users"), "UsersSettingsPage");
const DirectorySettingsPage = lazyRouteComponent(() => import("./routes/settings/directory"), "DirectorySettingsPage");
const ImportDataPage = lazyRouteComponent(() => import("./routes/settings/import-data"), "ImportDataPage");
const JiraImportPage = lazyRouteComponent(() => import("./routes/settings/jira-import"), "JiraImportPage");
const ConfluenceImportPage = lazyRouteComponent(() => import("./routes/settings/confluence-import"), "ConfluenceImportPage");
const RolesSettingsPage = lazyRouteComponent(() => import("./routes/settings/roles"), "RolesSettingsPage");
const TeamsSettingsPage = lazyRouteComponent(() => import("./routes/settings/teams"), "TeamsSettingsPage");
const TimeloggingSettingsPage = lazyRouteComponent(() => import("./routes/settings/timelogging"), "TimeloggingSettingsPage");
const TokensSettingsPage = lazyRouteComponent(() => import("./routes/settings/tokens"), "TokensSettingsPage");
const AuditSettingsPage = lazyRouteComponent(() => import("./routes/settings/audit"), "AuditSettingsPage");
const BackupsSettingsPage = lazyRouteComponent(() => import("./routes/settings/backups"), "BackupsSettingsPage");
const PluginsSettingsPage = lazyRouteComponent(() => import("./routes/settings/plugins"), "PluginsSettingsPage");
const CannedSettingsPage = lazyRouteComponent(() => import("./routes/settings/canned"), "CannedSettingsPage");
const ScriptsSettingsPage = lazyRouteComponent(() => import("./routes/settings/scripts"), "ScriptsSettingsPage");
const VcsSettingsPage = lazyRouteComponent(() => import("./routes/settings/vcs"), "VcsSettingsPage");
const ServiceAccountsSettingsPage = lazyRouteComponent(() => import("./routes/settings/service-accounts"), "ServiceAccountsSettingsPage");
const AiSettingsPage = lazyRouteComponent(() => import("./routes/settings/ai"), "AiSettingsPage");
const StorageSettingsPage = lazyRouteComponent(() => import("./routes/settings/storage"), "StorageSettingsPage");
const EmailSettingsPage = lazyRouteComponent(() => import("./routes/settings/email"), "EmailSettingsPage");
const SignInSettingsPage = lazyRouteComponent(() => import("./routes/settings/sign-in"), "SignInSettingsPage");
const MonitoringSettingsPage = lazyRouteComponent(() => import("./routes/settings/monitoring"), "MonitoringSettingsPage");
const WebhooksSettingsPage = lazyRouteComponent(() => import("./routes/settings/webhooks"), "WebhooksSettingsPage");
const NotificationSettingsPage = lazyRouteComponent(() => import("./routes/settings/notifications"), "NotificationSettingsPage");
const ProfileSettingsPage = lazyRouteComponent(() => import("./routes/settings/profile"), "ProfileSettingsPage");
const InstanceSettingsPage = lazyRouteComponent(() => import("./routes/settings/instance"), "InstanceSettingsPage");
const PagesSettingsPage = lazyRouteComponent(() => import("./routes/settings/pages"), "PagesSettingsPage");
const ViewPage = lazyRouteComponent(() => import("./routes/view"), "ViewPage");
const PagesIndexPage = lazyRouteComponent(() => import("./routes/pages-index"), "PagesIndexPage");
const PageSpacePage = lazyRouteComponent(() => import("./routes/page-space"), "PageSpacePage");
const PagePrintPage = lazyRouteComponent(() => import("./routes/page-print"), "PagePrintPage");
const DashboardPage = lazyRouteComponent(() => import("./routes/dashboard"), "DashboardPage");

/**
 * Code-based route tree. In-app routes are children of `appLayoutRoute` so
 * they inherit the shell and the auth gate. Issues are addressed by their
 * canonical key at the top-level `/issues/$itemKey` (spec 21) — the board no
 * longer nests a side-panel item route; a card navigates to the full page.
 * Settings sections nest under `settingsRoute` (secondary-nav layout);
 * /settings itself redirects to the first section.
 */

export interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.login,
  validateSearch: (search: Record<string, unknown>): { next?: string } => ({
    next: typeof search.next === "string" && search.next ? search.next : undefined,
  }),
  component: LoginPage,
});

/** PUBLIC tokened form submit (spec 62) — root-level like /login, no auth gate. */

/** PUBLIC tokened CSAT rating page (spec 65) — same idiom; the survey email's
 * links carry `?rating=N` to preselect a star (the page still POSTs). */
const publicCsatRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.publicCsat,
  validateSearch: (search: Record<string, unknown>): { rating?: number } => {
    const rating = Number(search.rating);
    return Number.isInteger(rating) && rating >= 1 && rating <= 5 ? { rating } : {};
  },
  component: PublicCsatPage,
});

const legacyKbIndexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.legacyKb,
  beforeLoad: () => {
    throw redirect({ to: RoutePath.pages, replace: true });
  },
  component: () => null,
});

const legacyKbSpaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.legacyKbSpace,
  beforeLoad: ({ params }) => {
    throw redirect({ to: RoutePath.pageSpace, params, replace: true });
  },
  component: () => null,
});

const legacyKbPageRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.legacyKbPage,
  beforeLoad: ({ params }) => {
    throw redirect({
      to: RoutePath.page,
      params: { spaceSlug: params.spaceSlug, _splat: params.pageSlug },
      replace: true,
    });
  },
  component: () => null,
});

/** Pathless layout: auth gate + app shell for every in-app route. */
const appLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  // `?peek=<itemKey>` opens the issue side panel over ANY in-app route (spec 25).
  // Inherited by every child route, so clicking an issue stays on the current
  // view and the browser Back button just closes the panel.
  validateSearch: (search: Record<string, unknown>): { peek?: string } => ({
    peek: typeof search.peek === "string" && search.peek ? search.peek : undefined,
  }),
  beforeLoad: async ({ context, location }) => {
    const authState = await context.queryClient.ensureQueryData(authStateQuery);
    if (authState.status === AuthStatus.unauthenticated) {
      throw redirect({ to: RoutePath.login, search: { next: location.href } });
    }
    // Spec 121: `anonymous` renders the shell for a visitor; personal routes
    // below add `requireAccount`.
    return { authState };
  },
  component: AppLayout,
});

/** Spec 121: a route only an account can use — a visitor is sent to sign in,
 *  carrying the page. */
async function requireAccount({
  context,
  location,
}: {
  context: { queryClient: QueryClient };
  location: { href: string };
}) {
  const authState = await context.queryClient.ensureQueryData(authStateQuery);
  if (authState.status !== AuthStatus.authenticated) {
    throw redirect({ to: RoutePath.login, search: { next: location.href } });
  }
}

/** Spec 121: "/" is My Work for an account and the projects index for a visitor. */
async function visitorToProjects({ context }: { context: { queryClient: QueryClient } }) {
  const authState = await context.queryClient.ensureQueryData(authStateQuery);
  if (authState.status === AuthStatus.anonymous) {
    throw redirect({ to: RoutePath.projects });
  }
}

/** "My Work" — the personal landing dashboard (spec 32). */
const myWorkRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.home,
  beforeLoad: visitorToProjects,
  component: MyWorkPage,
});

const starredRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.starred,
  beforeLoad: visitorToProjects,
  component: StarredPage,
});

const projectsIndexRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.projects,
  component: ProjectsIndexPage,
});

const projectRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.project,
  component: ProjectHomePage,
});

/** Canonical, key-addressed issue page (`/issues/TD-1234`) — spec 21. */
const issueRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.issue,
  component: ItemDetailPage,
});

/**
 * Catch-all plugin page (spec 94, the `route.page` slot): any in-app path not matched by an
 * explicit route above lands here, and the plugin whose federated `route.page` contribution matches
 * the pathname renders its page (milestones CRUD, the example plugin's Notes page, …). Explicit
 * routes always win over this splat, so it never shadows a builtin page.
 */
const pluginPageRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: "$",
  component: PluginPage,
});

/** Saved views (spec 09): project-scoped and all-projects. */
const projectViewRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.projectView,
  component: ViewPage,
});

const allProjectsViewRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.allProjectsView,
  component: ViewPage,
});

/** A cycle's items page (spec 18) — cycles span projects. */
const cycleRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.cycle,
  component: CyclePage,
});

/** Intake form submit page (spec 20) — `/p/$projectKey/forms/$formId`. */
const formSubmitRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.formSubmit,
  beforeLoad: requireAccount,
  component: FormSubmitPage,
});

/** LEGACY roadmap path (spec 79): roadmaps are saved views now — this route
 * stays registered so old links redirect to the project's first roadmap view. */
const roadmapRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.roadmap,
  component: RoadmapPage,
});

/** Project reporting dashboard (spec 19). */
const projectReportsRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.projectReports,
  component: ReportsPage,
});

/** Server-wide reporting — velocity across cycles (spec 19). */
const globalReportsRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.reports,
  component: GlobalReportsPage,
});

/** The timesheet — day/week/month time reports (spec 22). */
const timesheetRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.timesheet,
  beforeLoad: requireAccount,
  component: TimesheetPage,
});

/** Personal notification inbox (spec 26). */
const inboxRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.inbox,
  beforeLoad: requireAccount,
  component: InboxPage,
});

/** Requester portal (spec 73): the intake-form directory + a form's submit page. */
const portalRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.portal,
  beforeLoad: requireAccount,
  component: PortalPage,
});

const portalFormRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.portalForm,
  beforeLoad: requireAccount,
  component: PortalFormPage,
});

/** A composable dashboard's widget grid (spec 75). */
const dashboardRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.dashboard,
  component: DashboardPage,
});

/** Pages (spec 43): spaces index, a space's two-pane tree, the canonical page URL. */
const docsIndexRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.pages,
  component: PagesIndexPage,
  // `?pageId=<number>` is the page PERMALINK (RADD-1233): the index resolves
  // it and redirects to the page's current path. The OPTIONAL key keeps
  // `search` optional on every plain link to the index.
  validateSearch: (search: Record<string, unknown>): { pageId?: string | number } => ({
    pageId:
      typeof search.pageId === "number"
        ? search.pageId
        : typeof search.pageId === "string" && search.pageId
          ? search.pageId
          : undefined,
  }),
});

const docSpaceRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.pageSpace,
  component: PageSpacePage,
  // `?archived=1` opens the space's archive browser (RADD-1228). Same
  // normalisation as the print route: the router JSON-parses search values.
  // The OPTIONAL key is what keeps `search` optional on every existing link.
  validateSearch: (search: Record<string, unknown>): { archived?: true } => ({
    archived:
      search.archived === true || search.archived === 1 || search.archived === "1"
        ? true
        : undefined,
  }),
});

const pageRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.page,
  component: PageSpacePage,
});

/** RADD-733. Parented to the ROOT, not the app layout: the top bar, pins bar,
 *  sidebar and tree rail are precisely what a printed page must not contain. */
const pagePrintRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.pagePrint,
  component: PagePrintPage,
  // The router JSON-parses search values, so `?subpages=1` arrives as the
  // NUMBER 1 — comparing against the string silently dropped the key and the
  // router then rewrote the address bar without it, so "export with subpages"
  // exported one page. Normalise to a boolean and accept every spelling.
  validateSearch: (search: Record<string, unknown>) => ({
    subpages:
      search.subpages === true || search.subpages === 1 || search.subpages === "1"
        ? true
        : undefined,
  }),
});

const settingsRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.settings,
  beforeLoad: requireAccount,
  component: SettingsLayout,
});

/** Catch-all under Settings (spec 94): a plugin's `settings.page` slot renders here, inside the
 *  Settings chrome. Explicit settings routes win over this splat. */
const settingsPluginPageRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "$",
  component: SettingsPluginPage,
});

const settingsIndexRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: "/",
  beforeLoad: () => {
    // Profile, not Fields (RADD-788). Fields is gated on `field.manage`, which
    // most people do not hold — so the first click into Settings answered with a
    // permission toast. Profile is the one section every signed-in account can
    // open, which is what an index redirect has to land on.
    throw redirect({ to: RoutePath.settingsProfile });
  },
});

/** Personal profile (spec 34). */
const settingsProfileRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.profile,
  component: ProfileSettingsPage,
});

/** Instance settings (spec 50) — instance-admin only (nav-gated + API 403). */
const settingsInstanceRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.instance,
  component: InstanceSettingsPage,
});

/** Instance-scope scalar defaults (spec 50). */
const settingsGeneralRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.general,
  component: GeneralSettingsPage,
});

const settingsFieldsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.fields,
  component: FieldsSettingsPage,
});

const settingsLinkTypesRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.linkTypes,
  component: LinkTypesSettingsPage,
});

const settingsLabelsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.labels,
  component: LabelsSettingsPage,
});

const settingsCyclesRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.cycles,
  component: CyclesSettingsPage,
});

/** RADD-931: the mirror table folded into Settings → Directory, where the live
 *  browse already was — and gained the role-grant control it never had. */
const settingsGroupsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.groups,
  beforeLoad: () => {
    throw redirect({ to: RoutePath.settingsDirectory, replace: true });
  },
});

const settingsTeamsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.teams,
  component: TeamsSettingsPage,
});

/** Instance user administration (spec 84) — instance-admin only (nav-gated + API 403). */
const settingsUsersRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.users,
  component: UsersSettingsPage,
});

/** Consolidated Directory/LDAP settings (spec 85) — instance-admin only. */
const settingsDirectoryRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.directory,
  component: DirectorySettingsPage,
});

/** Jira import wizard (spec 90) — instance-admin only. */
const settingsImportDataRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.importData,
  component: ImportDataPage,
});
const settingsJiraImportRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.jiraImport,
  component: JiraImportPage,
});

/** Confluence import wizard (spec 117) — instance-admin only. */
const settingsConfluenceImportRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.confluenceImport,
  component: ConfluenceImportPage,
});

const settingsRolesRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.roles,
  component: RolesSettingsPage,
});

const settingsTokensRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.tokens,
  component: TokensSettingsPage,
});

/** Per-user notification rules (spec 118) — every signed-in account. */
const settingsNotificationsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.notifications,
  component: NotificationSettingsPage,
});

const settingsAutomationsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.automations,
  component: AutomationsSettingsPage,
});

const settingsTimeloggingRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.timelogging,
  component: TimeloggingSettingsPage,
});

const settingsAuditRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.audit,
  component: AuditSettingsPage,
  // Spec 123: every filter rides in the URL so an auditor can share a view and
  // a settings page can deep-link the trail for what it shows (RADD-1171).
  validateSearch: (search: Record<string, unknown>): AuditSearch => parseAuditSearch(search),
});

const settingsBackupsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.backups,
  component: BackupsSettingsPage,
});

const settingsPluginsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.plugins,
  component: PluginsSettingsPage,
});

/** Scripts (RADD-1269): the managed interpreter, its packages, the script library. */
const settingsScriptsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.scripts,
  component: ScriptsSettingsPage,
});

/** Canned responses admin (spec 30). */
const settingsCannedRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.canned,
  component: CannedSettingsPage,
});

/** Version control hosts (RADD-1262): one page, a tab per kind, `?host=` picks it. */
const settingsVcsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.vcs,
  validateSearch: (search: Record<string, unknown>): { host?: string } => ({
    host:
      search.host === SettingsSection.forgejo ||
      search.host === SettingsSection.github ||
      search.host === SettingsSection.gitlab
        ? search.host
        : undefined,
  }),
  component: VcsSettingsPage,
});

/** The pre-RADD-1262 per-kind paths: bookmarks and audit "change history"
 * links keep working, landing on the right tab. */
const settingsForgejoRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.forgejo,
  beforeLoad: () => {
    throw redirect({ to: RoutePath.settingsVcs, search: { host: SettingsSection.forgejo }, replace: true });
  },
});
const settingsGithubRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.github,
  beforeLoad: () => {
    throw redirect({ to: RoutePath.settingsVcs, search: { host: SettingsSection.github }, replace: true });
  },
});
const settingsGitlabRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.gitlab,
  beforeLoad: () => {
    throw redirect({ to: RoutePath.settingsVcs, search: { host: SettingsSection.gitlab }, replace: true });
  },
});

/** Service accounts + scoped keys (spec 113). */
const settingsServiceAccountsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.serviceAccounts,
  component: ServiceAccountsSettingsPage,
});

/** Page spaces admin (spec 43). */
const settingsDocsRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.pages,
  component: PagesSettingsPage,
});

/** AI providers/roles/toggles/presets (spec 101) — instance-admin only. */
const settingsAiRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.ai,
  component: AiSettingsPage,
});

/** Attachment storage hosts (spec 102) — instance-admin only. */
const settingsStorageRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.storage,
  component: StorageSettingsPage,
});

/** Mail sources, senders and the routing chain (RADD-958) — instance-admin only. */
const settingsEmailRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.email,
  component: EmailSettingsPage,
});

/** SSO providers + signup domain allowlists (spec 110) — instance-admin only. */
const settingsSignInRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.signIn,
  component: SignInSettingsPage,
});

/** Operator monitoring (DB health / counts / workers) — instance-admin only. */
const settingsMonitoringRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.monitoring,
  component: MonitoringSettingsPage,
});

/** Outbound webhooks (RADD-1096): endpoint CRUD + the delivery log. */
const settingsWebhooksRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.webhooks,
  component: WebhooksSettingsPage,
});

/** RADD-932: holidays merged into Settings → Time logging, beside the working
 *  week they interrupt. The path stays registered so a bookmark lands on the
 *  section rather than a not-found. */
const settingsHolidaysRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.holidays,
  beforeLoad: () => {
    throw redirect({ to: RoutePath.settingsTimelogging, replace: true });
  },
});

/**
 * Per-project settings (spec 50): nested under the project so the sub-nav is
 * gated by THAT project's permissions and the project is read from the URL.
 * `/p/$projectKey/settings` itself opens the first section the actor may manage.
 */
const projectSettingsRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.projectSettings,
  beforeLoad: requireAccount,
  component: ProjectSettingsLayout,
});

const projectSettingsIndexRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: "/",
  component: ProjectSettingsIndex,
});

const projectSettingsGeneralRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: ProjectSettingsSection.general,
  component: ProjectGeneralSettings,
});

const projectSettingsAccessRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: ProjectSettingsSection.access,
  component: ProjectAccessSettings,
});

const projectSettingsTypesRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: ProjectSettingsSection.types,
  component: ProjectTypesSettings,
});

const projectSettingsScreensRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: ProjectSettingsSection.screens,
  component: ProjectScreensSettings,
});

const projectSettingsWorkflowRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: ProjectSettingsSection.workflow,
  component: ProjectWorkflowSettings,
});

const projectSettingsReleasesRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: ProjectSettingsSection.releases,
  component: ProjectReleasesSettings,
});

const projectSettingsFormsRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: ProjectSettingsSection.forms,
  component: ProjectFormsSettings,
});

const projectSettingsTimeloggingRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: ProjectSettingsSection.timelogging,
  component: ProjectTimeloggingSettings,
});

/** SLA policies for the project (spec 67 — moved out of global settings). */
const projectSettingsSlaRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: ProjectSettingsSection.sla,
  component: ProjectSlaSettings,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  publicCsatRoute,
  pagePrintRoute,
  legacyKbIndexRoute,
  legacyKbSpaceRoute,
  legacyKbPageRoute,
  appLayoutRoute.addChildren([
    myWorkRoute,
    starredRoute,
    projectsIndexRoute,
    projectRoute,
    issueRoute,
    projectViewRoute,
    allProjectsViewRoute,
    cycleRoute,
    formSubmitRoute,
    roadmapRoute,
    projectReportsRoute,
    globalReportsRoute,
    timesheetRoute,
    inboxRoute,
    portalRoute,
    portalFormRoute,
    dashboardRoute,
    docsIndexRoute,
    docSpaceRoute,
    pageRoute,
    projectSettingsRoute.addChildren([
      projectSettingsIndexRoute,
      projectSettingsGeneralRoute,
      projectSettingsWorkflowRoute,
      projectSettingsTypesRoute,
      projectSettingsScreensRoute,
      projectSettingsAccessRoute,
      projectSettingsReleasesRoute,
      projectSettingsFormsRoute,
      projectSettingsTimeloggingRoute,
      projectSettingsSlaRoute,
    ]),
    settingsRoute.addChildren([
      settingsIndexRoute,
      settingsProfileRoute,
      settingsInstanceRoute,
      settingsGeneralRoute,
      settingsFieldsRoute,
      settingsLinkTypesRoute,
      settingsLabelsRoute,
      settingsCyclesRoute,
      settingsGroupsRoute,
      settingsTeamsRoute,
      settingsUsersRoute,
      settingsDirectoryRoute,
      settingsImportDataRoute,
      settingsJiraImportRoute,
      settingsConfluenceImportRoute,
      settingsRolesRoute,
      settingsTokensRoute,
      settingsNotificationsRoute,
      settingsAutomationsRoute,
      settingsTimeloggingRoute,
      settingsAuditRoute,
      settingsBackupsRoute,
      settingsPluginsRoute,
      settingsCannedRoute,
      settingsScriptsRoute,
      settingsVcsRoute,
      settingsForgejoRoute,
      settingsGithubRoute,
      settingsGitlabRoute,
      settingsServiceAccountsRoute,
      settingsDocsRoute,
      settingsAiRoute,
      settingsStorageRoute,
  settingsEmailRoute,
      settingsSignInRoute,
      settingsMonitoringRoute,
    settingsWebhooksRoute,
      settingsHolidaysRoute,
      // Splat LAST under settings so explicit settings pages win; plugin settings.page slots
      // render here (inside the Settings chrome). Spec 94.
      settingsPluginPageRoute,
    ]),
    // Splat LAST so every explicit route matches first (spec 94 plugin route pages).
    pluginPageRoute,
  ]),
]);

export function createAppRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: "intent",
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
