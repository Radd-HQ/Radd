/** Query keys — the single source of truth; never inline key arrays elsewhere. */

import type { CycleStatusValue } from "../types";

/** Query keys — the single source of truth; never inline key arrays elsewhere. */
export const queryKeys = {
  authState: ["auth", "me"] as const,
  projects: ["projects"] as const,
  states: (projectId: string) => ["states", { projectId }] as const,
  allStates: ["states", "all"] as const,
  transitions: (projectId: string) => ["transitions", { projectId }] as const,
  allowedTransitions: (itemId: string) => ["allowedTransitions", { itemId }] as const,
  issueTypes: (projectId: string) => ["issue-types", { projectId }] as const,
  effectiveScreen: (projectId: string, issueTypeId: string | null) =>
    ["screen-effective", { projectId, issueTypeId }] as const,
  screenConfig: (projectId: string, issueTypeId: string | null) =>
    ["screen-config", { projectId, issueTypeId }] as const,
  items: (projectId: string, archived = false) => ["items", { projectId, archived }] as const,
  itemsInfinite: (projectId: string, archived = false) =>
    ["itemsInfinite", { projectId, archived }] as const,
  item: (itemId: string) => ["item", { itemId }] as const,
  itemByKey: (key: string) => ["itemByKey", { key }] as const,
  comments: (itemId: string) => ["comments", { itemId }] as const,
  fields: ["fields"] as const,
  linkTypes: ["linkTypes"] as const,
  roleGrants: ["roleGrants"] as const,
  grants: ["grants"] as const,
  labels: ["labels"] as const,
  users: ["users"] as const,
  usersAdmin: (filters: Record<string, string>) => ["usersAdmin", filters] as const,
  userDuplicates: ["userDuplicates"] as const,
  ldapGroups: (q: string) => ["ldapGroups", { q }] as const,
  ldapDirectoryUsers: (q: string) => ["ldapDirectoryUsers", { q }] as const,
  ldapSyncStatus: ["ldapSyncStatus"] as const,
  teams: ["teams"] as const,
  teamMembers: (teamId: string) => ["teamMembers", { teamId }] as const,
  projectTeams: (projectId: string) => ["projectTeams", { projectId }] as const,
  tokens: ["tokens"] as const,
  views: ["views"] as const,
  viewCounts: (viewIds: readonly string[], extraQ?: string) =>
    ["viewCounts", { viewIds, extraQ: extraQ ?? "" }] as const,
  cardLayoutPresets: ["cardLayoutPresets"] as const,
  dashboards: ["dashboards"] as const,
  dashboard: (dashboardId: string) => ["dashboard", { dashboardId }] as const,
  itemsCount: (scope: Record<string, string>, q: string) =>
    ["itemsCount", { scope, q }] as const,
  slqListItems: (scope: Record<string, string>, q: string, limit: number) =>
    ["slqListItems", { scope, q, limit }] as const,
  viewItems: (viewId: string, queryString: string) =>
    ["viewItems", { viewId, queryString }] as const,
  itemIds: (queryString: string) => ["itemIds", { queryString }] as const,
  roadmapTray: (viewId: string, q: string, projectId: string, page: number) =>
    ["roadmapTray", { viewId, q, projectId, page }] as const,
  roadmapMembers: (viewId: string) => ["roadmapMembers", { viewId }] as const,
  viewItemsPage: (viewId: string, queryString: string, page: number) =>
    ["viewItemsPage", { viewId, queryString, page }] as const,
  slqItems: (scope: Record<string, string>, q: string) => ["slqItems", { scope, q }] as const,
  slqValidate: (projectId: string | null, q: string) =>
    ["slqValidate", { projectId, q }] as const,
  permissionsCatalog: ["permissionsCatalog"] as const,
  roles: ["roles"] as const,
  roleGlobalGrants: (roleId: string) => ["roles", roleId, "global-grants"] as const,
  projectMembers: (projectId: string) => ["projectMembers", { projectId }] as const,
  cycles: (status?: CycleStatusValue) => ["cycles", { status: status ?? null }] as const,
  cycle: (cycleId: string) => ["cycle", { cycleId }] as const,
  releases: (projectId: string) => ["releases", { projectId }] as const,
  reportThroughput: (projectId: string, start: string, end: string, interval: string, q?: string) =>
    ["report", "throughput", { projectId, start, end, interval }, { q: q ?? "" }] as const,
  reportCumulativeFlow: (projectId: string, start: string, end: string, interval: string, q?: string) =>
    ["report", "cumulative-flow", { projectId, start, end, interval }, { q: q ?? "" }] as const,
  reportTimeInState: (projectId: string, kind: string | null, q?: string) =>
    ["report", "time-in-state", { projectId, kind: kind ?? null }, { q: q ?? "" }] as const,
  reportVelocity: (last: number, measure: string, q?: string) =>
    ["report", "velocity", { last, measure }, { q: q ?? "" }] as const,
  reportBurnup: (cycleId: string, measure: string, q?: string) =>
    ["report", "burnup", { cycleId, measure }, { q: q ?? "" }] as const,
  automations: ["automations"] as const,
  plugins: ["plugins"] as const,
  automationCatalog: ["automationCatalog"] as const,
  forms: (projectId: string) => ["forms", { projectId }] as const,
  form: (formId: string) => ["form", { formId }] as const,
  publicForm: (token: string) => ["publicForm", { token }] as const,
  portalForms: ["portalForms"] as const,
  portalForm: (formId: string) => ["portalForm", { formId }] as const,
  mailContact: (itemId: string) => ["mailContact", { itemId }] as const,
  itemApprovals: (itemId: string) => ["itemApprovals", { itemId }] as const,
  pendingApprovals: ["pendingApprovals"] as const,
  itemParticipants: (itemId: string) => ["itemParticipants", { itemId }] as const,
  publicCsat: (token: string) => ["publicCsat", { token }] as const,
  itemCsat: (itemId: string) => ["itemCsat", { itemId }] as const,
  itemTimelog: (itemId: string) => ["itemTimelog", { itemId }] as const,
  workCategories: (includeArchived: boolean) =>
    ["workCategories", { includeArchived }] as const,
  projectTimelogging: (projectId: string) => ["projectTimelogging", { projectId }] as const,
  timesheet: (params: Record<string, string | string[]>) => ["timesheet", params] as const,
  itemHistory: (itemId: string) => ["itemHistory", { itemId }] as const,
  itemWebLinks: (itemId: string) => ["itemWebLinks", { itemId }] as const,
  itemVcsLinks: (itemId: string) => ["itemVcsLinks", { itemId }] as const,
  linkSearch: (projectId: string, q: string, limit?: number) =>
    ["linkSearch", { projectId, q, limit: limit ?? null }] as const,
  audit: (params: Record<string, string>) => ["audit", params] as const,
  backupStatus: () => ["backupStatus"] as const,
  backups: () => ["backups"] as const,
  backupSchedules: () => ["backupSchedules"] as const,
  backupRun: (runId: string) => ["backupRun", { runId }] as const,
  notifications: (unread: boolean) => ["notifications", { unread }] as const,
  search: (q: string) => ["search", { q }] as const,
  attachments: (entityType: string, entityId: string) =>
    ["attachments", { entityType, entityId }] as const,
  cannedResponses: ["cannedResponses"] as const,
  childItems: (parentId: string) => ["items", "children", parentId] as const,
  forgejoConnections: ["forgejoConnections"] as const,
  forgejoRepos: ["forgejoRepos"] as const,
  serviceAccounts: ["serviceAccounts"] as const,
  serviceAccountKeys: (id: string) => ["serviceAccounts", id, "keys"] as const,
  slaPolicies: (projectId: string) => ["slaPolicies", { projectId }] as const,
  itemSla: (itemId: string) => ["itemSla", { itemId }] as const,
  slaBatch: (itemIds: readonly string[]) => ["slaBatch", { itemIds }] as const,
  rollupBatch: (itemIds: readonly string[]) => ["rollupBatch", { itemIds }] as const,
  timelogBatch: (itemIds: readonly string[]) => ["timelogBatch", { itemIds }] as const,
  reportSla: (projectId: string | null, weeks: number, q?: string) =>
    ["report", "sla", { projectId, weeks }, { q: q ?? "" }] as const,
  notificationsBadge: ["notificationsBadge"] as const,
  itemWatchers: (itemId: string) => ["itemWatchers", { itemId }] as const,
  pageSpaces: ["pageSpaces"] as const,
  pageExtensions: ["pageExtensions"] as const,
  pageBacklinks: (pageId: string) => ["pageBacklinks", { pageId }] as const,
  pages: (spaceId: string) => ["pages", { spaceId }] as const,
  page: (pageId: string) => ["page", { pageId }] as const,
  pageVersions: (pageId: string) => ["pageVersions", { pageId }] as const,
  pageVersion: (pageId: string, version: number) =>
    ["pageVersion", { pageId, version }] as const,
  pageItems: (pageId: string) => ["pageItems", { pageId }] as const,
  itemPages: (itemId: string) => ["itemPages", { itemId }] as const,
  pageByPath: (spaceSlug: string, pageSlug: string) =>
    ["pageByPath", { spaceSlug, pageSlug }] as const,
  docsSearch: (q: string) => ["docsSearch", { q }] as const,
  deflect: (q: string, projectId: string) => ["deflect", { q, projectId }] as const,
  totp: ["auth", "totp"] as const,
  aiStatus: ["aiStatus"] as const,
  // Editor AI (spec 103) — the curated action menu behind the editor's AI entry.
  aiEditorActions: ["aiEditorActions"] as const,
  // AI provider registry (spec 101) — Settings → AI.
  ssoProviders: ["ssoProviders"] as const,
  ssoKinds: ["ssoKinds"] as const,
  aiProviders: ["aiProviders"] as const,
  aiRoles: ["aiRoles"] as const,
  aiPresets: ["aiPresets"] as const,
  aiEmbeddingCoverage: ["aiEmbeddingCoverage"] as const,
  monitoringOverview: ["monitoringOverview"] as const,
  // Storage host registry + routing chain + move jobs (spec 102).
  storageHosts: ["storageHosts"] as const,
  storageRules: ["storageRules"] as const,
  storageUploadContext: ["storageUploadContext"] as const,
  storageMoveJobs: ["storageMoveJobs"] as const,
  storageMoveJob: (jobId: string) => ["storageMoveJob", { jobId }] as const,
  // Semantic "Ask" search (spec 103) — the palette's second mode.
  searchSemantic: (q: string) => ["searchSemantic", { q }] as const,
  // The signed-in user's server-side preferences dict (spec 94).
  mePreferences: ["auth", "me", "preferences"] as const,
  similarItems: (itemId: string) => ["similarItems", { itemId }] as const,
  // seedKey identifies the text's origin (a comment id), not the text itself.
  similarToText: (seedKey: string) => ["similarToText", { seedKey }] as const,
  // Jira import (specs 90, 100). The wizard used to inline these key arrays.
  jiraConnections: ["jiraConnections"] as const,
  jiraStatus: ["jiraStatus"] as const,
  jiraProjects: (connectionId: string | null) => ["jiraProjects", { connectionId }] as const,
  jiraSnapshots: ["jiraSnapshots"] as const,
  jiraSnapshot: (snapshotId: string) => ["jiraSnapshot", { snapshotId }] as const,
  jiraPlans: ["jiraPlans"] as const,
  jiraPlan: (planId: string) => ["jiraPlan", { planId }] as const,
  jiraPending: ["jiraPending"] as const,
  jiraRuns: ["jiraRuns"] as const,
  jiraRun: (runId: string) => ["jiraRun", { runId }] as const,
} as const;
