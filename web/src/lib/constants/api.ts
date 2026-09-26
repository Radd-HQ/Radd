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
  // RADD-1295: PUT (multipart `file`) / DELETE your uploaded picture.
  myAvatar: "/auth/me/avatar",
  /** POST starts / DELETE ends a read-only admin preview (RADD-836 U1). */
  viewAs: "/auth/view-as",
  // TOTP two-factor (spec 48): GET status / DELETE {code}; setup + confirm below.
  totp: "/auth/totp",
  totpSetup: "/auth/totp/setup",
  totpConfirm: "/auth/totp/confirm",
  totpRecoveryCodes: "/auth/totp/recovery-codes",
  // RADD-1279: the forced-enrolment hand-off — ticket, not session.
  mfaEnrollmentSetup: "/auth/mfa-enrollment/setup",
  mfaEnrollmentConfirm: "/auth/mfa-enrollment/confirm",
  users: "/users",
  /** The member-floor people list (RADD-769) — `/users` is the ADMIN directory
   *  and stays behind `user.manage`. Everything that merely needs to name
   *  somebody (pickers, `@`-mentions, "edited by") reads this one. */
  userDirectory: "/users/directory",
  // Duplicate-account candidates for the merge UI (spec 84, instance admin).
  usersDuplicates: "/users/duplicates",
  stateCategories: "/state-categories",
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
  forms: "/forms",
  // Requester portal (spec 73): eligibility-gated form directory, any authed user.
  portalForms: "/portal/forms",
  /** Requests you filed (RADD-785) — a SIBLING prefix, never /portal/forms/requests:
   *  a literal after `/{form_id}` is shadowed by it (RADD-761). */
  portalRequests: "/portal/requests",
  // Spec 22 consumers (time logging):
  workCategories: "/work-categories",
  timesheet: "/timesheet",
  // Audit log (admin) — read-only over the event stream.
  // Backups (spec 99) — instance admin only.
  backups: "/backups",
  // Personal notifications (spec 26).
  notifications: "/notifications",
  // The caller's per-type inbox/email channel matrix (spec 26; RADD-686).
  notificationPrefs: "/notifications/preferences",
  // Full-text + key search (spec 28).
  search: "/search",
  // RADD-1327: every registered searchable type, answered by its owner.
  searchEntities: "/search/entities",
  // KB deflection for the new-issue flow (spec 66).
  searchDeflect: "/search/deflect",
  // Semantic "Ask" search for the palette (spec 103).
  searchSemantic: "/search/semantic",
  // Service desk (spec 30).
  cannedResponses: "/canned-responses",
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
  // Similar issues for a TEXT seed (read-mode AI menu on comments).
  aiSimilar: "/ai/similar",
  // Editor AI (spec 103) — the curated action menu + the SSE writing stream.
  aiEditorActions: "/ai/editor/actions",
  aiEditorStream: "/ai/editor/stream",
  // UNAUTHENTICATED — the login page's buttons (label + kind only). The
  // provider registry's admin paths are the sso plugin's own (RADD-1380).
  ssoPublicProviders: "/auth/sso/providers",
  ssoLogin: "/auth/oidc/login",
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

/** Reporting endpoints (spec 19) — all under `/reports`. The SLA report is the slas plugin's own (RADD-1386). */
export const ApiReportPath = {
  throughput: "/reports/throughput",
  cumulativeFlow: "/reports/cumulative-flow",
  timeInState: "/reports/time-in-state",
  velocity: "/reports/velocity",
  burnup: "/reports/burnup",
} as const;

/** How the api client reacts to a 401 response. */
export const On401 = {
  /** Hard-redirect to /login (default for data fetching inside the app shell). */
  redirect: "redirect",
  /** Surface the ApiError to the caller (login form, auth-state probe). */
  throw: "throw",
} as const;
export type On401Value = (typeof On401)[keyof typeof On401];

/** Spec 113: a service account's keys. */
export const apiServiceAccountKeysPath = (id: string) => `${ApiPath.serviceAccounts}/${id}/keys`;
export const apiServiceAccountKeyPath = (accountId: string, keyId: string) =>
  `${ApiPath.serviceAccounts}/${accountId}/keys/${keyId}`;
