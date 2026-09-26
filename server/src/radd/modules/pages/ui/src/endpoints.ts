/** The wiki's API vocabulary (spec 43): what the pages plugin's routers serve. */

export const PageApi = {
  spaces: "/page-spaces",
  templates: "/page-templates",
  pages: "/pages",
  extensions: "/pages/extensions",
  search: "/pages/search",
  /** Rebuild backlinks and issue links from every live page. */
  reindex: "/pages/reindex",
} as const;

export const spacePath = (spaceId: string) => `${PageApi.spaces}/${spaceId}`;
export const spacePagesPath = (spaceId: string) => `${spacePath(spaceId)}/pages`;
/** Spec 121 §5: the space's public-access switch. */
export const spacePublicAccessPath = (spaceId: string) => `${spacePath(spaceId)}/public-access`;
/** Spec 121 §5: a public space's shareable URL is its ORDINARY wiki URL. */
export const spacePublicUrl = (spaceSlug: string) => `${window.location.origin}/pages/${spaceSlug}`;

export const pagePath = (pageId: string) => `${PageApi.pages}/${pageId}`;
/** RADD-1296: tick a checklist box in the body. */
export const pageTasksPath = (pageId: string) => `${pagePath(pageId)}/tasks`;
export const pageUnarchivePath = (pageId: string) => `${pagePath(pageId)}/unarchive`;
export const pageRestorePath = (pageId: string) => `${pagePath(pageId)}/restore`;
export const pageVersionsPath = (pageId: string) => `${pagePath(pageId)}/versions`;
export const pageVersionPath = (pageId: string, version: number) => `${pageVersionsPath(pageId)}/${version}`;
export const pageItemsPath = (pageId: string) => `${pagePath(pageId)}/items`;
export const pageItemPath = (pageId: string, itemId: string) => `${pageItemsPath(pageId)}/${itemId}`;
/** What links here (RADD-713). */
export const pageBacklinksPath = (pageId: string) => `${pagePath(pageId)}/backlinks`;
/** Full replacement (RADD-718). */
export const pageLabelsPath = (pageId: string) => `${pagePath(pageId)}/labels`;
/** The self-maintaining index (RADD-718). */
export const pagesByLabelPath = (name: string) => `${PageApi.pages}/by-label/${encodeURIComponent(name)}`;
/** The page and its subtree as a markdown zip (RADD-721). */
export const pageExportPath = (pageId: string) => `${pagePath(pageId)}/export`;
/** GET/PUT/DELETE watching (RADD-719). */
export const pageWatchPath = (pageId: string) => `${pagePath(pageId)}/watch`;
/** Pages linked to an issue (the issue page's Pages row). */
export const itemPagesPath = (itemId: string) => `/items/${itemId}/pages`;

/** A page's comments: the comments API's route for a registered parent (RADD-717). */
export const pageCommentsPath = (pageId: string) => `/page/${pageId}/comments`;
/** One comment, and its checklist ticks and resolution (the comments API). */
export const commentPath = (commentId: string) => `/comments/${commentId}`;
export const commentTasksPath = (commentId: string) => `${commentPath(commentId)}/tasks`;

/** localStorage: a space's expanded tree node ids (JSON string[]). */
export const treeExpandStorageKey = (spaceId: string) => `radd.docs.${spaceId}.expanded`;

/** The issue page — where a linked issue opens. */
export const ISSUE_ROUTE = "/issues/$itemKey";
