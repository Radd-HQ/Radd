/** The wiki's queries (spec 43). Also read by the host — the permission union, the pins bar, the
 *  palette, an issue's Pages row and the editor's insert menu — through this package's export. */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api, ApiError, Entity, entityMeta } from "@radd/plugin-sdk";
import { encodePath } from "./links";
import {
  PageApi, itemPagesPath, pageBacklinksPath, pageItemsPath, pagePath, pageVersionPath, pageVersionsPath,
  pageWatchPath, pagesByLabelPath, spacePagesPath,
} from "./endpoints";
import type {
  ItemPageRef, Page, PageBacklink, PageExtensionSpec, PageLabelled, PageLinkedItem, PageSearchResponse,
  PageSpace, PageSummary, PageTemplate, DocVersion, PageVersionMeta,
} from "./types";


export const pageKeys = {
  spaces: ["pageSpaces"] as const,
  extensions: ["pageExtensions"] as const,
  backlinks: (pageId: string) => ["pageBacklinks", { pageId }] as const,
  watch: (pageId: string) => ["pageWatch", { pageId }] as const,
  byLabel: (name: string, space: string) => ["pagesByLabel", { name, space }] as const,
  pages: (spaceId: string) => ["pages", { spaceId }] as const,
  archived: (spaceId: string) => ["pagesArchived", { spaceId }] as const,
  page: (pageId: string) => ["page", { pageId }] as const,
  versions: (pageId: string) => ["pageVersions", { pageId }] as const,
  version: (pageId: string, version: number) => ["pageVersion", { pageId, version }] as const,
  items: (pageId: string) => ["pageItems", { pageId }] as const,
  itemPages: (itemId: string) => ["itemPages", { itemId }] as const,
  byPath: (spaceSlug: string, path: string) => ["pageByPath", { spaceSlug, path }] as const,
  byKey: (key: string) => ["pageByKey", { key }] as const,
  search: (q: string, limit?: number) => ["docsSearch", { q, limit }] as const,
};

export interface PageSpaceSummary { total: number; permissions: string[] }
export const PAGE_SPACES_PAGE_SIZE = 50;

/** How many spaces there are, and the caller's permission union across them (any member). */
export const pageSpaceSummaryQuery = () => queryOptions({
  queryKey: [...pageKeys.spaces, "summary"] as const,
  meta: entityMeta(Entity.docSpace, Entity.role, "team", "group", "member", "accessGrant"),
  staleTime: 30_000,
  queryFn: ({ signal }) => api.get<PageSpaceSummary>(`${PageApi.spaces}/summary`, { signal }),
});

export const pageSpacesPageQuery = (q = "", page = 0) => ({
  queryKey: [...pageKeys.spaces, "directory", q.trim(), page] as const,
  meta: entityMeta(Entity.docSpace, Entity.role),
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getPaged<PageSpace>(PageApi.spaces, { signal, query: {
    q: q.trim(), limit: String(PAGE_SPACES_PAGE_SIZE), offset: String(page * PAGE_SPACES_PAGE_SIZE),
  } }),
});

/** A space by slug or id; null when there is none (a 404 is an answer, not an error). */
export const pageSpaceByIdentityQuery = (identifier: string) => queryOptions({
  queryKey: [...pageKeys.spaces, "identity", identifier] as const,
  meta: entityMeta(Entity.docSpace, Entity.role),
  queryFn: async ({ signal }): Promise<PageSpace | null> => {
    try { return await api.get<PageSpace>(`${PageApi.spaces}/by-identity/${encodeURIComponent(identifier)}`, { signal }); }
    catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; }
  },
  enabled: Boolean(identifier),
});

/** What the editor's insert menu offers. A function of what is INSTALLED, so it is fetched rather
 *  than hardcoded — and cached indefinitely, since the set changes only with the plugins. */
export const pageExtensionsQuery = queryOptions({
  queryKey: pageKeys.extensions,
  queryFn: ({ signal }) => api.get<PageExtensionSpec[]>(PageApi.extensions, { signal }),
  staleTime: Infinity,
});

/** What links to this page (RADD-713) — an indexed lookup, not a corpus scan. */
export const pageBacklinksQuery = (pageId: string) => queryOptions({
  queryKey: pageKeys.backlinks(pageId),
  meta: entityMeta(Entity.page),
  queryFn: ({ signal }) => api.get<PageBacklink[]>(pageBacklinksPath(pageId), { signal }),
});

/** Every page carrying a label (RADD-718) — optionally scoped to one space. */
export const pagesByLabelQuery = (name: string, space = "") => queryOptions({
  queryKey: pageKeys.byLabel(name, space),
  meta: entityMeta(Entity.page),
  queryFn: ({ signal }) => api.get<PageLabelled[]>(pagesByLabelPath(name), { ...(space ? { query: { space } } : undefined), signal }),
});

/** Whether the current user is watching this page (RADD-719). */
export const pageWatchQuery = (pageId: string) => queryOptions({
  queryKey: pageKeys.watch(pageId),
  queryFn: ({ signal }) => api.get<{ watching: boolean }>(pageWatchPath(pageId), { signal }),
});

/** A space's flat page rows — the tree component assembles the hierarchy. */
export const pagesQuery = (spaceId: string) => queryOptions({
  queryKey: pageKeys.pages(spaceId),
  meta: entityMeta(Entity.page),
  queryFn: ({ signal }) => api.get<PageSummary[]>(spacePagesPath(spaceId), { signal }),
});

/** The whole space INCLUDING archived subtrees (RADD-1228) — the archive browser's rows.
 *  `page.manage` on the server; only ask when the actor holds it. */
export const archivedPagesQuery = (spaceId: string) => queryOptions({
  queryKey: pageKeys.archived(spaceId),
  meta: entityMeta(Entity.page),
  queryFn: ({ signal }) => api.get<PageSummary[]>(spacePagesPath(spaceId), { signal, query: { include_archived: "true" } }),
});

/** Full page: body + space + breadcrumb (the canonical page view). */
export const pageQuery = (pageId: string) => queryOptions({
  queryKey: pageKeys.page(pageId),
  meta: entityMeta(Entity.page),
  queryFn: ({ signal }) => api.get<Page>(pagePath(pageId), { signal }),
  retry: false,
});

/** A page by its URL address (`<space>/<path>`); the answer's `path` is canonical and the view redirects to it. */
export const pageByPathQuery = (spaceSlug: string, path: string) => queryOptions({
  queryKey: pageKeys.byPath(spaceSlug, path),
  meta: entityMeta(Entity.page),
  queryFn: ({ signal }) =>
    api.get<Page>(`${PageApi.pages}/by-path/${encodeURIComponent(spaceSlug)}/${encodePath(path)}`, { signal }),
  retry: false,
});

/** The permalink lookup (RADD-1233): `?pageId=<number>`, or a UUID for links minted before pages
 *  were numbered. */
export const pageByKeyQuery = (key: string) => queryOptions({
  queryKey: pageKeys.byKey(key),
  meta: entityMeta(Entity.page),
  queryFn: ({ signal }) =>
    /^\d+$/.test(key)
      ? api.get<Page>(`${PageApi.pages}/by-number/${key}`, { signal })
      : api.get<Page>(pagePath(key), { signal }),
  retry: false,
});

/** Version history metadata (newest first). */
export const pageVersionsQuery = (pageId: string) => queryOptions({
  queryKey: pageKeys.versions(pageId),
  meta: entityMeta(Entity.page),
  queryFn: ({ signal }) => api.get<PageVersionMeta[]>(pageVersionsPath(pageId), { signal }),
});

/** One version's full content (the history viewer). Versions are immutable. */
export const pageVersionQuery = (pageId: string, version: number) => queryOptions({
  queryKey: pageKeys.version(pageId, version),
  queryFn: ({ signal }) => api.get<DocVersion>(pageVersionPath(pageId, version), { signal }),
  staleTime: Infinity,
});

/** Issues linked to a page, hydrated (key/title/state), RBAC-filtered. */
export const pageItemsQuery = (pageId: string) => queryOptions({
  queryKey: pageKeys.items(pageId),
  meta: entityMeta(Entity.page, Entity.item),
  queryFn: ({ signal }) => api.get<PageLinkedItem[]>(pageItemsPath(pageId), { signal }),
});

/** Pages linked to an issue — the issue page's Pages row. */
export const itemPagesQuery = (itemId: string) => queryOptions({
  queryKey: pageKeys.itemPages(itemId),
  meta: entityMeta(Entity.page),
  queryFn: ({ signal }) => api.get<ItemPageRef[]>(itemPagesPath(itemId), { signal }),
  retry: false,
});

/** Page FTS for the palette's "Pages" section and any search box. */
export const pageSearchQuery = (q: string, limit: number) => queryOptions({
  queryKey: pageKeys.search(q, limit),
  meta: entityMeta(Entity.page),
  queryFn: ({ signal }) => api.get<PageSearchResponse>(PageApi.search, { signal, query: { q, limit: String(limit) } }),
  placeholderData: keepPreviousData,
  enabled: q.trim().length > 0,
});

export type PageTemplateSummary = Omit<PageTemplate, "body"> & { space_name: string | null };
export const PAGE_TEMPLATES_PAGE_SIZE = 50;
export const pageTemplatesPageQuery = (q: string, page: number) => ({
  queryKey: ["page-templates", "directory", q.trim(), page] as const,
  meta: entityMeta(Entity.docSpace, Entity.role),
  queryFn: ({ signal }: { signal: AbortSignal }) => api.getPaged<PageTemplateSummary>(`${PageApi.templates}/directory`, { signal, query: {
    q: q.trim(), limit: String(PAGE_TEMPLATES_PAGE_SIZE), offset: String(page * PAGE_TEMPLATES_PAGE_SIZE),
  } }),
});
export const pageTemplateByIdQuery = (id: string) => queryOptions({
  queryKey: ["page-templates", "detail", id] as const,
  meta: entityMeta(Entity.docSpace, Entity.role),
  queryFn: ({ signal }) => api.get<PageTemplate>(`${PageApi.templates}/${encodeURIComponent(id)}`, { signal }),
  enabled: Boolean(id),
});
