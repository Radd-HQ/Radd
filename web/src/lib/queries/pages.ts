/** Pages (docs module — spec 43). */

import { commentFeedQuery, CommentSection, type CommentSectionValue } from "./comment-feed";
import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiPageBacklinksPath,
  apiPageWatchPath,
  apiParentCommentsPath,
  apiPagesByLabelPath,
  apiPageItemsPath,
  apiPagePath,
  apiPageVersionPath,
  apiPageVersionsPath,
  apiPageSpacePagesPath,
  apiItemPagesPath,
} from "../constants";
import { queryKeys } from "./shared";
import { encodePath } from "../page-links";
import type {
  PageLinkedItem,
  PageTemplate,
  Page,
  PageBacklink,
  Comment,
  PageLabelled,
  PageExtensionSpec,
  PageSummary,
  PageSearchResponse,
  PageSpace,
  DocVersion,
  PageVersionMeta,
  ItemPageRef,
} from "../types";

// ---------------------------------------------------------------------------
// Pages (docs module — spec 43)
// ---------------------------------------------------------------------------

/** All page spaces with live page counts (any member: doc.read). */
export const pageSpacesQuery = () =>
  queryOptions({
    queryKey: queryKeys.pageSpaces,
    meta: entityMeta(Entity.docSpace),
    queryFn: ({ signal }) => api.get<PageSpace[]>(ApiPath.pageSpaces, { signal }),
  });

export interface PageSpaceSummary { total: number; permissions: string[] }
export const PAGE_SPACES_PAGE_SIZE = 50;
export const pageSpaceSummaryQuery = () => queryOptions({
  queryKey: [...queryKeys.pageSpaces, "summary"] as const,
  meta: entityMeta(Entity.docSpace, Entity.role, Entity.team, Entity.group, Entity.member, Entity.accessGrant),
  staleTime: 30_000,
  queryFn: ({ signal }) => api.get<PageSpaceSummary>(`${ApiPath.pageSpaces}/summary`, { signal }),
});
export const pageSpacesPageQuery = (q = "", page = 0) => queryOptions({
  queryKey: [...queryKeys.pageSpaces, "directory", q.trim(), page] as const,
  meta: entityMeta(Entity.docSpace, Entity.role),
  queryFn: ({ signal }) => api.getPaged<PageSpace>(ApiPath.pageSpaces, { signal, query: {
    q: q.trim(), limit: String(PAGE_SPACES_PAGE_SIZE), offset: String(page * PAGE_SPACES_PAGE_SIZE),
  } }),
});
export const pageSpaceByIdentityQuery = (identifier: string) => queryOptions({
  queryKey: [...queryKeys.pageSpaces, "identity", identifier] as const,
  meta: entityMeta(Entity.docSpace, Entity.role),
  queryFn: async ({ signal }): Promise<PageSpace | null> => {
    try { return await api.get<PageSpace>(`${ApiPath.pageSpaces}/by-identity/${encodeURIComponent(identifier)}`, { signal }); }
    catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; }
  },
  enabled: Boolean(identifier),
});

/** What the editor's insert menu offers. A function of what is INSTALLED, so it
 *  is fetched rather than hardcoded — and cached indefinitely, because the set
 *  only changes when a plugin is mounted or unmounted. */
export const pageExtensionsQuery = queryOptions({
  queryKey: queryKeys.pageExtensions,
  queryFn: ({ signal }) => api.get<PageExtensionSpec[]>(ApiPath.pageExtensions, { signal }),
  staleTime: Infinity,
});

/** What links to this page (RADD-713) — an indexed lookup, not a corpus scan. */
export const pageBacklinksQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.pageBacklinks(pageId),
    meta: entityMeta(Entity.page),
    queryFn: ({ signal }) => api.get<PageBacklink[]>(apiPageBacklinksPath(pageId), { signal }),
  });

/** Every page carrying a label (RADD-718) — optionally scoped to one space. */
export const pagesByLabelQuery = (name: string, space = "") =>
  queryOptions({
    queryKey: queryKeys.pagesByLabel(name, space),
    meta: entityMeta(Entity.page),
    queryFn: ({ signal }) =>
      api.get<PageLabelled[]>(apiPagesByLabelPath(name), { ...(space ? { query: { space } } : undefined), signal: signal }),
  });

/** A page's discussion (RADD-717) — the same comments table issues use. */
export const pageCommentsQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.pageComments(pageId),
    meta: entityMeta(Entity.comment),
    queryFn: ({ signal }) => api.get<Comment[]>(apiParentCommentsPath("page", pageId), { signal }),
  });

/** Whether the current user is watching this page (RADD-719). */
export const pageWatchQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.pageWatch(pageId),
    queryFn: ({ signal }) => api.get<{ watching: boolean }>(apiPageWatchPath(pageId), { signal }),
  });

/** A space's flat page rows — the tree component assembles the hierarchy. */
export const pagesQuery = (spaceId: string) =>
  queryOptions({
    queryKey: queryKeys.pages(spaceId),
    meta: entityMeta(Entity.page),
    queryFn: ({ signal }) => api.get<PageSummary[]>(apiPageSpacePagesPath(spaceId), { signal }),
  });

/** The whole space INCLUDING archived subtrees (RADD-1228) — the archive
 *  browser's rows. `page.manage` on the server; only ask when the actor holds it. */
export const archivedPagesQuery = (spaceId: string) =>
  queryOptions({
    queryKey: queryKeys.pagesArchived(spaceId),
    meta: entityMeta(Entity.page),
    queryFn: ({ signal }) =>
      api.get<PageSummary[]>(apiPageSpacePagesPath(spaceId), {
        signal,
        query: { include_archived: "true" },
      }),
  });

/** Full page: body + space + breadcrumb (the canonical page view). */
export const pageQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.page(pageId),
    meta: entityMeta(Entity.page),
    queryFn: ({ signal }) => api.get<Page>(apiPagePath(pageId), { signal }),
    retry: false,
  });

/** A page addressed the way the URL addresses it (RADD-702, RADD-1233):
 *  `<space>/<slug>/<slug>/…`. The space may be an id; a single page segment
 *  may be a number or an id; a stale path resolves through the page's old
 *  addresses. The answer carries the canonical `path`, and the view redirects
 *  to it when the address it arrived by differs. */
export const pageByPathQuery = (spaceSlug: string, path: string) =>
  queryOptions({
    queryKey: queryKeys.pageByPath(spaceSlug, path),
    meta: entityMeta(Entity.page),
    queryFn: ({ signal }) =>
      api.get<Page>(`${ApiPath.pages}/by-path/${encodeURIComponent(spaceSlug)}/${encodePath(path)}`, { signal }),
    retry: false,
  });

/** The permalink lookup (RADD-1233): `?pageId=<number>`, or a UUID for links
 *  minted before pages were numbered. */
export const pageByKeyQuery = (key: string) =>
  queryOptions({
    queryKey: queryKeys.pageByKey(key),
    meta: entityMeta(Entity.page),
    queryFn: ({ signal }) =>
      /^\d+$/.test(key)
        ? api.get<Page>(`${ApiPath.pages}/by-number/${key}`, { signal })
        : api.get<Page>(apiPagePath(key), { signal }),
    retry: false,
  });

/** Version history metadata (newest first). */
export const pageVersionsQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.pageVersions(pageId),
    meta: entityMeta(Entity.page),
    queryFn: ({ signal }) => api.get<PageVersionMeta[]>(apiPageVersionsPath(pageId), { signal }),
  });

/** One version's full content (the history viewer). */
export const pageVersionQuery = (pageId: string, version: number) =>
  queryOptions({
    queryKey: queryKeys.pageVersion(pageId, version),
    queryFn: ({ signal }) => api.get<DocVersion>(apiPageVersionPath(pageId, version), { signal }),
    staleTime: Infinity, // versions are immutable
  });

/** Issues linked to a page, hydrated (key/title/state), RBAC-filtered. */
export const pageItemsQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.pageItems(pageId),
    meta: entityMeta(Entity.page, Entity.item),
    queryFn: ({ signal }) => api.get<PageLinkedItem[]>(apiPageItemsPath(pageId), { signal }),
  });

/** Pages linked to an issue — the issue page's Pages row. */
export const itemPagesQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemPages(itemId),
    meta: entityMeta(Entity.page),
    queryFn: ({ signal }) => api.get<ItemPageRef[]>(apiItemPagesPath(itemId), { signal }),
    retry: false,
  });

/** Doc FTS for the palette's "Pages" section + any search box. */
export const pageSearchQuery = (q: string, limit: number) =>
  queryOptions({
    queryKey: queryKeys.docsSearch(q, limit),
    meta: entityMeta(Entity.page),
    queryFn: ({ signal }) =>
      api.get<PageSearchResponse>(ApiPath.docsSearch, {
        signal,
        query: { q, limit: String(limit) },
      }),
    placeholderData: keepPreviousData,
    enabled: q.trim().length > 0,
  });

export const pageCommentFeedQuery = (
  pageId: string, section: CommentSectionValue = CommentSection.discussion, unresolvedOnly = false,
) => commentFeedQuery(queryKeys.pageComments(pageId), apiParentCommentsPath("page", pageId), section, unresolvedOnly);


export type PageTemplateSummary = Omit<PageTemplate, "body"> & { space_name: string | null };
export const PAGE_TEMPLATES_PAGE_SIZE = 50;
export const pageTemplatesPageQuery = (q: string, page: number) => queryOptions({
  queryKey: ["page-templates", "directory", q.trim(), page] as const,
  meta: entityMeta(Entity.docSpace, Entity.role),
  queryFn: ({ signal }) => api.getPaged<PageTemplateSummary>(`${ApiPath.pageTemplates}/directory`, { signal, query: {
    q: q.trim(), limit: String(PAGE_TEMPLATES_PAGE_SIZE), offset: String(page * PAGE_TEMPLATES_PAGE_SIZE),
  } }),
});
export const pageTemplateByIdQuery = (id: string) => queryOptions({
  queryKey: ["page-templates", "detail", id] as const,
  meta: entityMeta(Entity.docSpace, Entity.role),
  queryFn: ({ signal }) => api.get<PageTemplate>(`${ApiPath.pageTemplates}/${encodeURIComponent(id)}`, { signal }),
  enabled: Boolean(id),
});
