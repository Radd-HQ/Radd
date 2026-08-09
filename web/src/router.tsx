import {
  Outlet,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  redirect,
} from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";
import { AuthStatus } from "./lib/auth";
import { ProjectSettingsSection, RoutePath, SettingsSection } from "./lib/constants";
import { authStateQuery } from "./lib/queries";
import { AppLayout } from "./routes/app-layout";
import { PluginPage } from "./components/shell/PluginPage";
import { SettingsPluginPage } from "./components/shell/SettingsPluginPage";
import { CyclePage } from "./routes/cycle";
import { FormSubmitPage } from "./routes/form-submit";
import { ItemDetailPage } from "./routes/item-page";
import { LoginPage } from "./routes/login";
import { MyWorkPage } from "./routes/my-work";
import { ProjectHomePage } from "./routes/project-home";
import { ProjectsIndexPage } from "./routes/projects-index";
import { PublicCsatPage } from "./routes/public-csat";
import { PublicPagesIndexPage, PublicPageSpacePage } from "./routes/public-pages";
import { RoadmapPage } from "./routes/roadmap";
import { ReportsPage } from "./routes/reports";
import { GlobalReportsPage } from "./routes/global-reports";
import { TimesheetPage } from "./routes/timesheet";
import { InboxPage } from "./routes/inbox";
import { PortalPage } from "./routes/portal";
import { PortalFormPage } from "./routes/portal-form";
import { SettingsLayout } from "./routes/settings/layout";
import {
  ProjectSettingsLayout,
  ProjectGeneralSettings,
  ProjectAccessSettings,
  ProjectWorkflowSettings,
  ProjectTypesSettings,
  ProjectScreensSettings,
  ProjectReleasesSettings,
  ProjectFormsSettings,
  ProjectTimeloggingSettings,
  ProjectSlaSettings,
} from "./routes/project-settings/layout";
import { GeneralSettingsPage } from "./routes/settings/general";
import { AutomationsSettingsPage } from "./routes/settings/automations";
import { CyclesSettingsPage } from "./routes/settings/cycles";
import { FieldsSettingsPage } from "./routes/settings/fields";
import { LinkTypesSettingsPage } from "./routes/settings/link-types";
import { LabelsSettingsPage } from "./routes/settings/labels";
import { UsersSettingsPage } from "./routes/settings/users";
import { DirectorySettingsPage } from "./routes/settings/directory";
import { JiraImportPage } from "./routes/settings/jira-import";
import { ConfluenceImportPage } from "./routes/settings/confluence-import";
import { RolesSettingsPage } from "./routes/settings/roles";
import { TeamsSettingsPage } from "./routes/settings/teams";
import { TimeloggingSettingsPage } from "./routes/settings/timelogging";
import { TokensSettingsPage } from "./routes/settings/tokens";
import { AuditSettingsPage } from "./routes/settings/audit";
import { BackupsSettingsPage } from "./routes/settings/backups";
import { PluginsSettingsPage } from "./routes/settings/plugins";
import { CannedSettingsPage } from "./routes/settings/canned";
import { ForgejoSettingsPage } from "./routes/settings/forgejo";
import { ServiceAccountsSettingsPage } from "./routes/settings/service-accounts";
import { AiSettingsPage } from "./routes/settings/ai";
import { StorageSettingsPage } from "./routes/settings/storage";
import { EmailSettingsPage } from "./routes/settings/email";
import { SignInSettingsPage } from "./routes/settings/sign-in";
import { MonitoringSettingsPage } from "./routes/settings/monitoring";
import { ProfileSettingsPage } from "./routes/settings/profile";
import { InstanceSettingsPage } from "./routes/settings/instance";
import { PagesSettingsPage } from "./routes/settings/pages";
import { ViewPage } from "./routes/view";
import { PagesIndexPage } from "./routes/pages-index";
import { PageSpacePage } from "./routes/page-space";
import { PagePrintPage } from "./routes/page-print";
import { DashboardPage } from "./routes/dashboard";

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

/** PUBLIC pages (spec 74) — same idiom: root-level, no auth gate.
 * Space cards, a space's tree (first page auto-selected), a canonical page. */
const publicKbIndexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.publicPages,
  component: PublicPagesIndexPage,
});

const publicKbSpaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.publicPageSpace,
  component: PublicPageSpacePage,
});

// Kept until V1: the instance is public and old /kb links live in the wild (RADD-896).
const legacyKbIndexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.legacyKb,
  beforeLoad: () => {
    throw redirect({ to: RoutePath.publicPages, replace: true });
  },
  component: () => null,
});

const legacyKbSpaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.legacyKbSpace,
  beforeLoad: ({ params }) => {
    throw redirect({ to: RoutePath.publicPageSpace, params, replace: true });
  },
  component: () => null,
});

const legacyKbPageRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.legacyKbPage,
  beforeLoad: ({ params }) => {
    throw redirect({ to: RoutePath.publicPage, params, replace: true });
  },
  component: () => null,
});

const publicKbPageRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: RoutePath.publicPage,
  component: PublicPageSpacePage,
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
  beforeLoad: async ({ context }) => {
    const authState = await context.queryClient.ensureQueryData(authStateQuery);
    if (authState.status === AuthStatus.unauthenticated) {
      throw redirect({ to: RoutePath.login });
    }
    return { authState };
  },
  component: AppLayout,
});

/** "My Work" — the personal landing dashboard (spec 32). */
const myWorkRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.home,
  component: MyWorkPage,
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
  component: TimesheetPage,
});

/** Personal notification inbox (spec 26). */
const inboxRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.inbox,
  component: InboxPage,
});

/** Requester portal (spec 73): the intake-form directory + a form's submit page. */
const portalRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.portal,
  component: PortalPage,
});

const portalFormRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.portalForm,
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
});

const docSpaceRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.pageSpace,
  component: PageSpacePage,
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

/** Canned responses admin (spec 30). */
const settingsCannedRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.canned,
  component: CannedSettingsPage,
});

/** Forgejo hosts + repositories (spec 111). */
const settingsForgejoRoute = createRoute({
  getParentRoute: () => settingsRoute,
  path: SettingsSection.forgejo,
  component: ForgejoSettingsPage,
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
 * `/p/$projectKey/settings` itself redirects to the first section (workflow).
 */
const projectSettingsRoute = createRoute({
  getParentRoute: () => appLayoutRoute,
  path: RoutePath.projectSettings,
  component: ProjectSettingsLayout,
});

const projectSettingsIndexRoute = createRoute({
  getParentRoute: () => projectSettingsRoute,
  path: "/",
  beforeLoad: ({ params }) => {
    throw redirect({
      to: RoutePath.projectSettingsWorkflow,
      params: { projectKey: (params as { projectKey: string }).projectKey },
    });
  },
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
  publicKbIndexRoute,
  publicKbSpaceRoute,
  publicKbPageRoute,
  pagePrintRoute,
  legacyKbIndexRoute,
  legacyKbSpaceRoute,
  legacyKbPageRoute,
  appLayoutRoute.addChildren([
    myWorkRoute,
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
      settingsJiraImportRoute,
      settingsConfluenceImportRoute,
      settingsRolesRoute,
      settingsTokensRoute,
      settingsAutomationsRoute,
      settingsTimeloggingRoute,
      settingsAuditRoute,
      settingsBackupsRoute,
      settingsPluginsRoute,
      settingsCannedRoute,
      settingsForgejoRoute,
      settingsServiceAccountsRoute,
      settingsDocsRoute,
      settingsAiRoute,
      settingsStorageRoute,
  settingsEmailRoute,
      settingsSignInRoute,
      settingsMonitoringRoute,
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
