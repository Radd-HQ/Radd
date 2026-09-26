/** API base + endpoint paths, and the api client's 401 behavior. Contracts: specs 01–03 + /openapi.json. */

export const API_BASE = "/api/v1";
/** API paths, relative to the versioned base. */
export const ApiPath = {
  login: "/auth/login",
  ldapLogin: "/auth/ldap/login",
  /** Second step for TOTP-enabled accounts: email+password+code. */
  loginTotp: "/auth/login/totp",
  logout: "/auth/logout",
  me: "/auth/me",
  // PUT (multipart `file`) / DELETE your uploaded picture.
  myAvatar: "/auth/me/avatar",
  /** POST starts / DELETE ends a read-only admin preview (RADD-836). */
  viewAs: "/auth/view-as",
  // TOTP: GET status / DELETE {code}; setup + confirm below.
  totp: "/auth/totp",
  totpSetup: "/auth/totp/setup",
  totpConfirm: "/auth/totp/confirm",
  totpRecoveryCodes: "/auth/totp/recovery-codes",
  // The forced-enrolment hand-off (RADD-1279) — ticket, not session.
  mfaEnrollmentSetup: "/auth/mfa-enrollment/setup",
  mfaEnrollmentConfirm: "/auth/mfa-enrollment/confirm",
  users: "/users",
  /** The member-floor people list (RADD-769) — `/users` is the ADMIN directory
   *  and stays behind `user.manage`. Everything that merely needs to name
   *  somebody (pickers, `@`-mentions, "edited by") reads this one. */
  userDirectory: "/users/directory",
  usersDuplicates: "/users/duplicates",
  stateCategories: "/state-categories",
  tokens: "/tokens",
  projects: "/projects",
  states: "/states",
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
  /** Mirrored directory groups (read-only — sync writes them). */
  groups: "/groups",
  comments: "/comments",
  views: "/views",
  roles: "/roles",
  permissions: "/permissions",
  cycles: "/cycles",
  releases: "/releases",
  forms: "/forms",
  // Requester portal: the eligibility-gated form directory, any signed-in user.
  portalForms: "/portal/forms",
  /** Requests you filed (RADD-785) — a SIBLING prefix, never /portal/forms/requests:
   *  a literal after `/{form_id}` is shadowed by it (RADD-761). */
  portalRequests: "/portal/requests",
  workCategories: "/work-categories",
  timesheet: "/timesheet",
  backups: "/backups",
  notifications: "/notifications",
  notificationPrefs: "/notifications/preferences",
  search: "/search",
  // Every registered searchable type, answered by its owner (RADD-1327).
  searchEntities: "/search/entities",
  // KB deflection for the new-issue flow.
  searchDeflect: "/search/deflect",
  cannedResponses: "/canned-responses",
  serviceAccounts: "/service-accounts",
  // Batched epic-progress rollup for board/list progress bars.
  itemsRollup: "/items/rollup",
  // Batched estimate/logged seconds (roadmap durations and tints).
  itemsTimelogBatch: "/items/timelog/batch",
  // Bulk operations + the "select all matching" id listing.
  itemsBulkUpdate: "/items/bulk-update",
  itemsBulkMove: "/items/bulk-move",
  itemsIds: "/items/ids",
  // The visible-match count alone — My Work's section counts.
  itemsCount: "/items/count",
  // Intake validation (spec 119), contributed by `automations`. The context read is three segments
  // deliberately: two would sit behind `GET /items/{item_id}`.
  itemsValidate: "/items/validate",
  itemsValidateContext: "/items/validate/context",
  // Batched view membership counts for a view type's own sidebar section.
  viewCounts: "/views/counts",
  // Card-layout preset library (spec 109) — shared, copy-on-apply.
  cardLayoutPresets: "/views/card-presets",
  // Safe instance config: the work week.
  instance: "/instance",
  // Backend-assembled UI manifest: capability flags + plugin nav.
  capabilities: "/capabilities",
  // GET list + POST {id}/{install,enable,disable,uninstall}.
  plugins: "/plugins",
  // Scalar settings cascade: GET/PUT/DELETE ?scope=&scope_id=.
  scopedSettings: "/scoped-settings",
  // One key's cascade-RESOLVED value — readable by any member.
  scopedSettingsResolve: "/scoped-settings/resolve",
  // The wiki's endpoints are the pages plugin's `PageApi` (RADD-1392).
  webhooks: "/webhooks",
  // UNAUTHENTICATED — the login page's buttons (label + kind only). The
  // provider registry's admin paths are the sso plugin's own (RADD-1380).
  ssoPublicProviders: "/auth/sso/providers",
  ssoLogin: "/auth/oidc/login",
  storageHosts: "/storage/hosts",
  // Storage routing chain + move jobs — instance admin.
  storageRules: "/storage/rules",
  // The rule types a new rule may use — the live socket providers.
  storageRuleTypes: "/storage/rule-types",
  storageRulesOrder: "/storage/rules/order",
  storageMoveJobs: "/storage/move-jobs",
  // Pre-upload storage context — any authenticated user.
  storageUploadContext: "/storage/upload-context",
  // The signed-in user's server-side preferences dict (shallow-merge PUT).
  mePreferences: "/auth/me/preferences",
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

/** A service account's keys. */
export const apiServiceAccountKeysPath = (id: string) => `${ApiPath.serviceAccounts}/${id}/keys`;
export const apiServiceAccountKeyPath = (accountId: string, keyId: string) =>
  `${ApiPath.serviceAccounts}/${accountId}/keys/${keyId}`;
