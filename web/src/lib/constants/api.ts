/** API base + endpoint paths, and the api client's 401 behavior. Contracts: specs 01–03 + /openapi.json. */

/** API paths, relative to the versioned base. Contracts: specs 01–03 + /openapi.json. */
export const API_BASE = "/api/v1";
export const ApiPath = {
  login: "/auth/login",
  ldapLogin: "/auth/ldap/login",
  /** Second step for TOTP-enabled accounts (spec 48): email+password+code. */
  loginTotp: "/auth/login/totp",
  logout: "/auth/logout",
  me: "/auth/me",
  /** POST starts / DELETE ends a read-only admin preview (RADD-836 U1). */
  viewAs: "/auth/view-as",
  // TOTP two-factor (spec 48): GET status / DELETE {code}; setup + confirm below.
  totp: "/auth/totp",
  totpSetup: "/auth/totp/setup",
  totpConfirm: "/auth/totp/confirm",
  totpRecoveryCodes: "/auth/totp/recovery-codes",
  users: "/users",
  /** The member-floor people list (RADD-769) — `/users` is the ADMIN directory
   *  and stays behind `user.manage`. Everything that merely needs to name
   *  somebody (pickers, `@`-mentions, "edited by") reads this one. */
  userDirectory: "/users/directory",
  // Duplicate-account candidates for the merge UI (spec 84, instance admin).
  usersDuplicates: "/users/duplicates",
  // Directory administration (spec 84, instance admin + bind account).
  ldapGroups: "/ldap/groups",
  ldapGroupsImport: "/ldap/groups/import",
  ldapDirectoryUsers: "/ldap/directory-users",
  ldapDirectoryUsersImport: "/ldap/directory-users/import",
  // Spec 88: dry run — classify the selection against existing accounts first.
  ldapDirectoryUsersImportPreview: "/ldap/directory-users/import/preview",
  // Spec 85: sync status rows + the on-demand user-sync pass (instance admin).
  ldapSyncStatus: "/ldap/sync-status",
  ldapSyncUsers: "/ldap/sync/users",
  ldapSyncGroups: "/ldap/sync/groups",
  stateCategories: "/state-categories",
  // Jira import wizard (spec 90) — instance admin.
  // Spec 100: connections are admin-managed rows, not environment variables.
  jiraConnections: "/jira/connections",
  // Spec 100: a JQL result set is downloaded ONCE into a cached snapshot, and
  // every later step reads that instead of hammering Jira again.
  jiraSnapshots: "/jira/snapshots",
  jiraStatus: "/jira/status",
  jiraProjects: "/jira/projects",
  jiraPreview: "/jira/preview",
  jiraPlans: "/jira/plans",
  jiraRuns: "/jira/runs",
  // Spec 100: cross-project references still waiting for their target.
  jiraPending: "/jira/pending",
  jiraRelink: "/jira/relink",
  // Confluence importer (spec 117). Same four phases as the Jira one.
  confluenceConnections: "/confluence/connections",
  confluenceStatus: "/confluence/status",
  confluenceSpaces: "/confluence/spaces",
  confluenceSnapshots: "/confluence/snapshots",
  confluencePlans: "/confluence/plans",
  confluenceRuns: "/confluence/runs",
  tokens: "/tokens",
  projects: "/projects",
  // Phase 2+ consumers:
  states: "/states",
  // Workflow transition rows (spec 61): POST/PATCH/DELETE.
  transitions: "/transitions",
  issueTypes: "/issue-types",
  screens: "/screens",
  screensEffective: "/screens/effective",
  items: "/items",
  labels: "/labels",
  fields: "/fields",
  linkTypes: "/link-types",
  roleGrants: "/role-grants",
  grants: "/grants",
  teams: "/teams",
  /** RADD-829: mirrored directory groups (read-only — sync writes them). */
  groups: "/groups",
  comments: "/comments",
  // Spec 06/08 consumers:
  views: "/views",
  roles: "/roles",
  permissions: "/permissions",
  // Spec 18 consumers:
  cycles: "/cycles",
  releases: "/releases",
  // Spec 20 consumers:
  automations: "/automations",
  forms: "/forms",
  // Requester portal (spec 73): eligibility-gated form directory, any authed user.
  portalForms: "/portal/forms",
  /** Requests you filed (RADD-785) — a SIBLING prefix, never /portal/forms/requests:
   *  a literal after `/{form_id}` is shadowed by it (RADD-761). */
  portalRequests: "/portal/requests",
  // Spec 22 consumers (time logging):
  workCategories: "/work-categories",
  timesheet: "/timesheet",
  leave: "/leave",
  leaveMine: "/leave/mine",
  leaveHolidays: "/leave/holidays",
  leaveCurrent: "/leave/current",
  leaveCalendar: "/leave/calendar",
  // Audit log (admin) — read-only over the event stream.
  audit: "/audit",
  auditCatalog: "/audit/catalog",
  // Backups (spec 99) — instance admin only.
  backups: "/backups",
  // Personal notifications (spec 26).
  notifications: "/notifications",
  // The caller's per-type inbox/email channel matrix (spec 26; RADD-686).
  notificationPrefs: "/notifications/preferences",
  // Full-text + key search (spec 28).
  search: "/search",
  // KB deflection for the new-issue flow (spec 66).
  searchDeflect: "/search/deflect",
  // Semantic "Ask" search for the palette (spec 103).
  searchSemantic: "/search/semantic",
  // Service desk (spec 30).
  cannedResponses: "/canned-responses",
  // Spec 111 — Forgejo hosts/repos as rows.
  forgejoConnections: "/forgejo/connections",
  forgejoRepos: "/forgejo/repos",
  githubConnections: "/github/connections",
  githubRepos: "/github/repos",
  // RADD-1253 — GitLab hosts/projects as rows.
  gitlabConnections: "/gitlab/connections",
  gitlabRepos: "/gitlab/repos",
  // Spec 113 — service accounts and their scoped keys.
  serviceAccounts: "/service-accounts",
  slaPolicies: "/sla-policies",
  // Batch SLA timers for list/board chips (spec 63).
  itemsSlaBatch: "/items/sla/batch",
  // Batched epic-progress rollup for board/list progress bars (spec 76).
  itemsRollup: "/items/rollup",
  // Batched estimate/logged seconds for roadmap auto-schedule durations (spec 78).
  itemsTimelogBatch: "/items/timelog/batch",
  // Bulk operations (spec 68): one patch/move across many items + the
  // "select all matching" id listing.
  itemsBulkUpdate: "/items/bulk-update",
  itemsBulkMove: "/items/bulk-move",
  itemsIds: "/items/ids",
  // The visible-match count alone (spec 75) — powers dashboard slq_count widgets.
  itemsCount: "/items/count",
  // Intake validation (spec 119). Contributed by `automations` under an
  // `/items` prefix; the context read is three segments deliberately, because
  // two would sit behind `GET /items/{item_id}`.
  itemsValidate: "/items/validate",
  itemsValidateContext: "/items/validate/context",
  // Composable dashboards (spec 75).
  dashboards: "/dashboards",
  // Batched view membership counts for the sidebar queue badges (spec 64).
  viewCounts: "/views/counts",
  // Card-layout preset library (spec 109) — shared, copy-on-apply.
  cardLayoutPresets: "/views/card-presets",
  // Safe instance config: the work week (spec 35).
  instance: "/instance",
  // Instance deploy status (spec 50) — instance-admin only.
  instanceStatus: "/instance/status",
  // Backend-assembled UI manifest (spec 93 / A7): capability flags + plugin nav.
  capabilities: "/capabilities",
  // Plugin manager (spec 93 / A4): GET list + POST {id}/{install,enable,disable,uninstall}.
  plugins: "/plugins",
  // Scalar settings cascade (spec 50): GET/PUT/DELETE ?scope=&scope_id=.
  scopedSettings: "/scoped-settings",
  // One key's cascade-RESOLVED value (spec 70) — readable by any member.
  scopedSettingsResolve: "/scoped-settings/resolve",
  // Builtin-field write rules (spec 36).
  // Approvals on workflow transitions (spec 71): my pending-approvals queue.
  approvalsPending: "/approvals/pending",
  // Pages (spec 43).
  pageSpaces: "/page-spaces",
  pageExtensions: "/pages/extensions",
  pageTemplates: "/page-templates",
  pages: "/pages",
  docsSearch: "/pages/search",
  // AI layer (spec 46) — the status gate + natural-language → SLQ.
  pagesReindex: "/pages/reindex",
  webhooks: "/webhooks",
  aiStatus: "/ai/status",
  aiLocalEmbed: "/ai/local-embed",
  // Similar issues for a TEXT seed (read-mode AI menu on comments).
  aiSimilar: "/ai/similar",
  // Editor AI (spec 103) — the curated action menu + the SSE writing stream.
  aiEditorActions: "/ai/editor/actions",
  aiEditorStream: "/ai/editor/stream",
  // AI provider registry (spec 101) — instance admin: providers, roles, presets.
  aiProviders: "/ai/providers",
  aiRoles: "/ai/roles",
  aiPresets: "/ai/presets",
  aiEmbeddingCoverage: "/ai/embeddings/coverage",
  // SSO provider registry (spec 110) — instance admin: Settings → Sign-in.
  ssoProviders: "/sso/providers",
  ssoKinds: "/sso/kinds",
  // UNAUTHENTICATED — the login page's buttons (label + kind only).
  ssoPublicProviders: "/auth/sso/providers",
  ssoLogin: "/auth/oidc/login",
  // Mail configuration (RADD-958/969) — instance admin: Settings → Email.
  mailSources: "/mail/sources",
  mailSenders: "/mail/senders",
  mailRules: "/mail/rules",
  /** Per-kind defaults — what the add-a-source/sender form prefills itself with. */
  mailKinds: "/mail/kinds",
  monitoringOverview: "/monitoring/overview",
  // Storage host registry (spec 102) — instance admin: Settings → Storage.
  storageHosts: "/storage/hosts",
  // Storage routing chain + move jobs (spec 102) — instance admin.
  storageRules: "/storage/rules",
  storageRulesOrder: "/storage/rules/order",
  storageMoveJobs: "/storage/move-jobs",
  // Pre-upload storage context (spec 102) — any authenticated user.
  storageUploadContext: "/storage/upload-context",
  // The signed-in user's server-side preferences dict (spec 94; shallow-merge PUT).
  mePreferences: "/auth/me/preferences",
  slqNl: "/slq/nl",
} as const;

/** Reporting endpoints (spec 19; sla — spec 63) — all under `/reports`. */
export const ApiReportPath = {
  throughput: "/reports/throughput",
  cumulativeFlow: "/reports/cumulative-flow",
  timeInState: "/reports/time-in-state",
  velocity: "/reports/velocity",
  burnup: "/reports/burnup",
  sla: "/reports/sla",
} as const;

/** How the api client reacts to a 401 response. */
export const On401 = {
  /** Hard-redirect to /login (default for data fetching inside the app shell). */
  redirect: "redirect",
  /** Surface the ApiError to the caller (login form, auth-state probe). */
  throw: "throw",
} as const;
export type On401Value = (typeof On401)[keyof typeof On401];

/** Spec 111: one Forgejo connection. */
export const apiForgejoConnectionPath = (id: string) => `${ApiPath.forgejoConnections}/${id}`;
export const apiForgejoConnectionTestPath = (id: string) =>
  `${ApiPath.forgejoConnections}/${id}/test`;
export const apiForgejoRepoPath = (id: string) => `${ApiPath.forgejoRepos}/${id}`;
export const apiForgejoBackfillPath = (id: string) => `${ApiPath.forgejoRepos}/${id}/backfill`;
export const apiGithubConnectionPath = (id: string) => `${ApiPath.githubConnections}/${id}`;
export const apiGithubConnectionTestPath = (id: string) =>
  `${ApiPath.githubConnections}/${id}/test`;
export const apiGithubRepoPath = (id: string) => `${ApiPath.githubRepos}/${id}`;
export const apiGithubBackfillPath = (id: string) => `${ApiPath.githubRepos}/${id}/backfill`;
export const apiGitlabConnectionPath = (id: string) => `${ApiPath.gitlabConnections}/${id}`;
export const apiGitlabConnectionTestPath = (id: string) =>
  `${ApiPath.gitlabConnections}/${id}/test`;
export const apiGitlabRepoPath = (id: string) => `${ApiPath.gitlabRepos}/${id}`;
export const apiGitlabBackfillPath = (id: string) => `${ApiPath.gitlabRepos}/${id}/backfill`;
/** RADD-1258: a connection's identity map and unmatched authors, per provider. */
export const apiVcsIdentitiesPath = (provider: string, connectionId: string) =>
  `/vcs/${provider}/connections/${connectionId}/identities`;
export const apiVcsIdentityPath = (linkId: string) => `/vcs/identities/${linkId}`;
export const apiVcsUnmatchedPath = (provider: string, connectionId: string) =>
  `/vcs/${provider}/connections/${connectionId}/unmatched`;
export const apiVcsUnmatchedReplayPath = (provider: string, connectionId: string) =>
  `${apiVcsUnmatchedPath(provider, connectionId)}/replay`;

/** Spec 113: a service account's keys. */
export const apiServiceAccountKeysPath = (id: string) => `${ApiPath.serviceAccounts}/${id}/keys`;
export const apiServiceAccountKeyPath = (accountId: string, keyId: string) =>
  `${ApiPath.serviceAccounts}/${accountId}/keys/${keyId}`;
