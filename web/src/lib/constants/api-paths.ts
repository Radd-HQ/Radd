/** Parameterized API paths (single source for interpolated URLs). */

import { API_BASE, ApiPath } from "./api";

/** Parameterized API paths (single source for interpolated URLs). */
export const apiItemPath = (itemId: string) => `${ApiPath.items}/${itemId}`;
/** Resolve an item by its canonical key (`TD-25`) — spec 21 backend resolver. */
export const apiItemByKeyPath = (key: string) =>
  `${ApiPath.items}/by-key/${encodeURIComponent(key)}`;
export const apiItemCommentsPath = (itemId: string) => `${ApiPath.items}/${itemId}/comments`;
/** RADD-717: comments on any registered parent, e.g. ("page", id). */
export const apiParentCommentsPath = (entityType: string, entityId: string) =>
  `/${entityType}/${entityId}/comments`;
export const apiCommentPath = (commentId: string) => `${ApiPath.comments}/${commentId}`;
export const apiStatePath = (stateId: string) => `${ApiPath.states}/${stateId}`;
export const apiTransitionPath = (transitionId: string) =>
  `${ApiPath.transitions}/${transitionId}`;
export const apiProjectTransitionsPath = (projectId: string) =>
  `${ApiPath.projects}/${projectId}/transitions`;
export const apiItemAllowedTransitionsPath = (itemId: string) =>
  `${ApiPath.items}/${itemId}/allowed-transitions`;
export const apiTokenPath = (tokenId: string) => `${ApiPath.tokens}/${tokenId}`;
export const apiUserPath = (userId: string) => `${ApiPath.users}/${userId}`;
/** GET — every atom this person holds, and which source supplied it (RADD-779). */
export const apiUserPermissionsPath = (userId: string) =>
  `${ApiPath.users}/${userId}/permissions`;
/** POST — fold the path user (the duplicate) into `into_user_id` (spec 84). */
export const apiUserMergePath = (userId: string) => `${ApiPath.users}/${userId}/merge`;
/** GET — what an account owns (spec 89); drives the delete dialog. */
export const apiUserContentPath = (userId: string) => `${ApiPath.users}/${userId}/content`;
export const apiTeamPath = (teamId: string) => `${ApiPath.teams}/${teamId}`;
/** POST — on-demand reconcile of a linked team against AD (spec 84). */
export const apiTeamDirectorySyncPath = (teamId: string) =>
  `${ApiPath.teams}/${teamId}/directory-sync`;
/** PUT — replace the team's managers, i.e. who may administer THIS team (spec 87). */
export const apiTeamManagersPath = (teamId: string) => `${ApiPath.teams}/${teamId}/managers`;
/** POST — hand the team to a new owner (spec 87). */
export const apiTeamTransferPath = (teamId: string) => `${ApiPath.teams}/${teamId}/transfer`;
export const apiTeamMembersPath = (teamId: string) => `${ApiPath.teams}/${teamId}/members`;
export const apiTeamMemberPath = (teamId: string, userId: string) =>
  `${ApiPath.teams}/${teamId}/members/${userId}`;
export const apiProjectTeamsPath = (projectId: string) => `${ApiPath.projects}/${projectId}/teams`;
export const apiProjectTeamPath = (projectId: string, teamId: string) =>
  `${ApiPath.projects}/${projectId}/teams/${teamId}`;
export const apiProjectMembersPath = (projectId: string) =>
  `${ApiPath.projects}/${projectId}/members`;
export const apiProjectMemberPath = (projectId: string, userId: string) =>
  `${ApiPath.projects}/${projectId}/members/${userId}`;
export const apiViewPath = (viewId: string) => `${ApiPath.views}/${viewId}`;
/** PUT — replace the view's full sharing state (spec 57). */
export const apiViewSharingPath = (viewId: string) => `${ApiPath.views}/${viewId}/sharing`;
/** POST — reassign the view's owner (spec 57). */
export const apiViewTransferPath = (viewId: string) => `${ApiPath.views}/${viewId}/transfer`;
/** PATCH/DELETE one card-layout preset (spec 109). */
export const apiCardLayoutPresetPath = (presetId: string) =>
  `${ApiPath.cardLayoutPresets}/${presetId}`;
/** Composable dashboards (spec 75) — sharing/transfer mirror the view paths. */
export const apiDashboardPath = (dashboardId: string) => `${ApiPath.dashboards}/${dashboardId}`;
export const apiDashboardSharingPath = (dashboardId: string) =>
  `${apiDashboardPath(dashboardId)}/sharing`;
export const apiDashboardTransferPath = (dashboardId: string) =>
  `${apiDashboardPath(dashboardId)}/transfer`;
export const apiDashboardWidgetsPath = (dashboardId: string) =>
  `${apiDashboardPath(dashboardId)}/widgets`;
export const apiDashboardWidgetPath = (dashboardId: string, widgetId: string) =>
  `${apiDashboardWidgetsPath(dashboardId)}/${widgetId}`;
export const apiRolePath = (roleId: string) => `${ApiPath.roles}/${roleId}`;
/** GET/PUT — who holds this role instance-wide (spec 87). */
export const apiRoleGlobalGrantsPath = (roleId: string) =>
  `${ApiPath.roles}/${roleId}/global-grants`;
export const apiCyclePath = (cycleId: string) => `${ApiPath.cycles}/${cycleId}`;
export const apiCycleCompletePath = (cycleId: string) => `${apiCyclePath(cycleId)}/complete`;
export const apiCycleStatsPath = (cycleId: string) => `${apiCyclePath(cycleId)}/stats`;
export const apiCycleSeriesPath = (seriesId: string) => `/cycle-series/${seriesId}`;
export const apiReleasePath = (releaseId: string) => `${ApiPath.releases}/${releaseId}`;
export const apiItemStarPath = (itemId: string) => `${ApiPath.items}/${itemId}/star`;
export const apiItemRankPath = (itemId: string) => `${ApiPath.items}/${itemId}/rank`;
export const apiItemArchivePath = (itemId: string) => `${ApiPath.items}/${itemId}/archive`;
export const apiItemLinksPath = (itemId: string) => `${ApiPath.items}/${itemId}/links`;
export const apiItemLinkPath = (itemId: string, linkId: string) =>
  `${ApiPath.items}/${itemId}/links/${linkId}`;
/** Per-item activity feed (History tab). */
export const apiItemHistoryPath = (itemId: string) => `${ApiPath.items}/${itemId}/history`;
/** Dependency-link typeahead (query: project_id, q, exclude_id?). */
export const apiItemLinkSearchPath = () => `${ApiPath.items}/link-search`;
/** Related/external links (weblinks module). */
export const apiItemWebLinksPath = (itemId: string) => `${ApiPath.items}/${itemId}/web-links`;
export const apiWebLinkPath = (linkId: string) => `/web-links/${linkId}`;
/** Version-control references (vcs module). */
export const apiItemVcsLinksPath = (itemId: string) => `${ApiPath.items}/${itemId}/vcs-links`;
export const apiVcsLinkPath = (linkId: string) => `/vcs-links/${linkId}`;
/** PUT here replaces the field's full grant list (spec 07). */
export const apiFieldPermissionsPath = (fieldId: string) =>
  `${ApiPath.fields}/${fieldId}/permissions`;
/** ADD options to a select field (additive-only — spec 100/107). */
export const apiFieldOptionsPath = (fieldId: string) =>
  `${ApiPath.fields}/${fieldId}/options`;
/** Automation rule paths (spec 20). */
export const apiAutomationPath = (ruleId: string) => `${ApiPath.automations}/${ruleId}`;
export const apiAutomationTestPath = (ruleId: string) =>
  `${ApiPath.automations}/${ruleId}/test`;
/** Intake form paths (spec 20). */
export const apiFormPath = (formId: string) => `${ApiPath.forms}/${formId}`;
export const apiFormSubmitPath = (formId: string) => `${ApiPath.forms}/${formId}/submit`;
/** PUT — replace the form's full portal share list (spec 73). */
export const apiFormSharingPath = (formId: string) => `${ApiPath.forms}/${formId}/sharing`;
/** Requester portal (spec 73): GET renders for an eligible actor, POST submits. */
export const apiPortalFormPath = (formId: string) => `${ApiPath.portalForms}/${formId}`;
export const apiPortalFormSubmitPath = (formId: string) =>
  `${ApiPath.portalForms}/${formId}/submit`;
/** Public (unauthenticated) form path (spec 62): GET renders, POST submits. */
export const apiPublicFormPath = (token: string) => `/public/forms/${encodeURIComponent(token)}`;
/** Tokened KB deflection for the public form page (spec 74) — docs only. */
export const apiPublicFormDeflectPath = (token: string) =>
  `${apiPublicFormPath(token)}/deflect`;
/** The shareable public submit URL shown in the form builder (spec 62). */
export const publicFormUrl = (token: string) =>
  `${window.location.origin}/public/forms/${encodeURIComponent(token)}`;
/** Public KB paths (spec 74): a public space's tree + one page's body. */
export const apiPublicPagesTreePath = (spaceId: string) =>
  `${ApiPath.publicKbSpaces}/${spaceId}/tree`;
export const apiPublicPagesPagePath = (pageId: string) => `/public/pages/pages/${pageId}`;
/** The shareable public-KB URL shown next to a space's Public toggle (spec 74). */
export const publicKbSpaceUrl = (spaceId: string) => `${window.location.origin}/kb/${spaceId}`;
/** The item's external requester (spec 62) — 404 when the item has none. */
export const apiItemMailContactPath = (itemId: string) =>
  `${ApiPath.items}/${itemId}/mail-contact`;
/** Public (unauthenticated) CSAT survey path (spec 65): GET renders, POST rates. */
export const apiPublicCsatPath = (token: string) => `/public/csat/${encodeURIComponent(token)}`;
/** The item's ANSWERED CSAT survey (spec 65) — 404 until the requester responds. */
export const apiItemCsatPath = (itemId: string) => `${ApiPath.items}/${itemId}/csat`;

/** Approvals on workflow transitions (spec 71). */
export const apiItemApprovalsPath = (itemId: string) => `${ApiPath.items}/${itemId}/approvals`;
export const apiApprovalPath = (requestId: string) => `/approvals/${requestId}`;
export const apiApprovalVotePath = (requestId: string) => `/approvals/${requestId}/vote`;

/** Request participants (spec 72): users + teams following an item. */
export const apiItemParticipantsPath = (itemId: string) =>
  `${ApiPath.items}/${itemId}/participants`;
export const apiItemParticipantPath = (itemId: string, participantId: string) =>
  `${apiItemParticipantsPath(itemId)}/${participantId}`;

/** Time-logging paths (spec 22). */
export const apiItemWorklogsPath = (itemId: string) => `${ApiPath.items}/${itemId}/worklogs`;
export const apiItemTimelogPath = (itemId: string) => `${ApiPath.items}/${itemId}/timelog`;
export const apiItemEstimatePath = (itemId: string) => `${ApiPath.items}/${itemId}/estimate`;
export const apiWorklogPath = (worklogId: string) => `/worklogs/${worklogId}`;
export const apiWorkCategoryPath = (categoryId: string) =>
  `${ApiPath.workCategories}/${categoryId}`;
export const apiProjectTimeloggingPath = (projectId: string) =>
  `${ApiPath.projects}/${projectId}/timelogging`;

/** Attachment paths (spec 29). Canonical collection is polymorphic: POST a
 * multipart upload with `entity_type`+`entity_id`, GET lists any parent's files
 * via the same query params. */
export const apiAttachmentsPath = () => "/attachments";
export const apiAttachmentPath = (attachmentId: string) => `/attachments/${attachmentId}`;
/** Absolute URL for embedding an attachment in markdown (image src / link href). */
export const attachmentUrl = (attachmentId: string) =>
  `${API_BASE}${apiAttachmentPath(attachmentId)}`;

/** Service-desk paths (spec 30). */
export const apiCannedResponsePath = (responseId: string) =>
  `${ApiPath.cannedResponses}/${responseId}`;
/** The body with `{{token}}` variables resolved against an item (spec 66). */
export const apiCannedRenderPath = (responseId: string) =>
  `${apiCannedResponsePath(responseId)}/render`;
export const apiSlaPolicyPath = (policyId: string) => `${ApiPath.slaPolicies}/${policyId}`;
export const apiItemSlaPath = (itemId: string) => `${ApiPath.items}/${itemId}/sla`;

/** Pages paths (spec 43). */
export const apiPageSpacePath = (spaceId: string) => `${ApiPath.pageSpaces}/${spaceId}`;
export const apiPageSpacePagesPath = (spaceId: string) => `${ApiPath.pageSpaces}/${spaceId}/pages`;
export const apiPagePath = (pageId: string) => `${ApiPath.pages}/${pageId}`;
export const apiPageUnarchivePath = (pageId: string) =>
  `${ApiPath.pages}/${pageId}/unarchive`;
export const apiPageVersionsPath = (pageId: string) =>
  `${ApiPath.pages}/${pageId}/versions`;
export const apiPageVersionPath = (pageId: string, version: number) =>
  `${ApiPath.pages}/${pageId}/versions/${version}`;
export const apiPageRestorePath = (pageId: string) => `${ApiPath.pages}/${pageId}/restore`;
export const apiPageItemsPath = (pageId: string) => `${ApiPath.pages}/${pageId}/items`;
export const apiPageItemPath = (pageId: string, itemId: string) =>
  `${ApiPath.pages}/${pageId}/items/${itemId}`;
/** Pages linked to an issue (the issue page's Pages row). */
export const apiItemDocsPath = (itemId: string) => `${ApiPath.items}/${itemId}/docs`;

/** AI paths (spec 46): on-demand summary + candidate duplicates for an item. */
export const apiItemAiSummarizePath = (itemId: string) =>
  `${ApiPath.items}/${itemId}/ai/summarize`;
/** SSE variant of summarize (the Stream-AI-responses instance setting). */
export const apiItemAiSummarizeStreamPath = (itemId: string) =>
  `${ApiPath.items}/${itemId}/ai/summarize/stream`;
export const apiItemSimilarPath = (itemId: string) => `${ApiPath.items}/${itemId}/similar`;
/** SSE: per-candidate LLM reasoning for a displayed similar list. */
export const apiItemAiSimilarReasonsPath = (itemId: string) =>
  `${ApiPath.items}/${itemId}/ai/similar/reasons`;

/** AI provider registry paths (spec 101) — instance admin only. */
export const apiAiProviderPath = (providerId: string) => `${ApiPath.aiProviders}/${providerId}`;
export const apiAiProviderTestPath = (providerId: string) =>
  `${apiAiProviderPath(providerId)}/test`;
export const apiAiRolePath = (role: string) => `${ApiPath.aiRoles}/${role}`;
export const apiAiPresetPath = (presetId: string) => `${ApiPath.aiPresets}/${presetId}`;

/** SSO provider paths (spec 110) — instance admin only. */
export const apiSsoProviderPath = (providerId: string) => `${ApiPath.ssoProviders}/${providerId}`;
export const apiSsoProviderTestPath = (providerId: string) =>
  `${apiSsoProviderPath(providerId)}/test`;
/** Where a login button points. No id = the only configured provider (spec 40 shape). */
export const ssoLoginPath = (providerId?: string) =>
  providerId ? `${ApiPath.ssoLogin}?provider_id=${providerId}` : ApiPath.ssoLogin;

/** Storage host paths (spec 102) — instance admin only. */
export const apiStorageHostPath = (hostId: string) => `${ApiPath.storageHosts}/${hostId}`;
export const apiStorageHostDefaultPath = (hostId: string) =>
  `${apiStorageHostPath(hostId)}/default`;
export const apiStorageHostHealthPath = (hostId: string) =>
  `${apiStorageHostPath(hostId)}/health`;
/** POST — move every attachment on this host to a target (spec 102). */
export const apiStorageHostMovePath = (hostId: string) =>
  `${apiStorageHostPath(hostId)}/move`;
export const apiStorageRulePath = (ruleId: string) => `${ApiPath.storageRules}/${ruleId}`;
export const apiStorageMoveJobPath = (jobId: string) => `${ApiPath.storageMoveJobs}/${jobId}`;

/** Notification + watcher paths (spec 26). */
export const apiNotificationsReadPath = () => `${ApiPath.notifications}/read`;
export const apiNotificationsReadAllPath = () => `${ApiPath.notifications}/read-all`;
export const apiItemWatchPath = (itemId: string) => `${ApiPath.items}/${itemId}/watch`;
export const apiItemWatchersPath = (itemId: string) => `${ApiPath.items}/${itemId}/watchers`;

/** GET /pages/{id}/backlinks — what links here (RADD-713). */
export const apiPageBacklinksPath = (pageId: string) => `/pages/${pageId}/backlinks`;

/** PUT /pages/{id}/labels — full replacement (RADD-718). */
export const apiPageLabelsPath = (pageId: string) => `/pages/${pageId}/labels`;

/** GET /pages/by-label/{name} — the self-maintaining index (RADD-718). */
export const apiPagesByLabelPath = (name: string) =>
  `/pages/by-label/${encodeURIComponent(name)}`;

/** GET /pages/{id}/export — the page and its subtree as a markdown zip (RADD-721). */
export const apiPageExportPath = (pageId: string) => `/pages/${pageId}/export`;

/** GET/PUT/DELETE /pages/{id}/watch (RADD-719). */
export const apiPageWatchPath = (pageId: string) => `/pages/${pageId}/watch`;
