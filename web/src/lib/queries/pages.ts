/** Pages (docs module — spec 43). */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiPageBacklinksPath,
  apiPageItemsPath,
  apiPagePath,
  apiPageVersionPath,
  apiPageVersionsPath,
  apiPageSpacePagesPath,
  apiItemDocsPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  PageLinkedItem,
  Page,
  PageBacklink,
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
    queryFn: () => api.get<PageSpace[]>(ApiPath.pageSpaces),
  });

/** What the editor's insert menu offers. A function of what is INSTALLED, so it
 *  is fetched rather than hardcoded — and cached indefinitely, because the set
 *  only changes when a plugin is mounted or unmounted. */
export const pageExtensionsQuery = queryOptions({
  queryKey: queryKeys.pageExtensions,
  queryFn: () => api.get<PageExtensionSpec[]>(ApiPath.pageExtensions),
  staleTime: Infinity,
});

/** What links to this page (RADD-713) — an indexed lookup, not a corpus scan. */
export const pageBacklinksQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.pageBacklinks(pageId),
    meta: entityMeta(Entity.page),
    queryFn: () => api.get<PageBacklink[]>(apiPageBacklinksPath(pageId)),
  });

/** A space's flat page rows — the tree component assembles the hierarchy. */
export const pagesQuery = (spaceId: string) =>
  queryOptions({
    queryKey: queryKeys.pages(spaceId),
    meta: entityMeta(Entity.page),
    queryFn: () => api.get<PageSummary[]>(apiPageSpacePagesPath(spaceId)),
  });

/** Full page: body + space + breadcrumb (the canonical page view). */
export const pageQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.page(pageId),
    meta: entityMeta(Entity.page),
    queryFn: () => api.get<Page>(apiPagePath(pageId)),
    retry: false,
  });

/** A page addressed the way the URL addresses it (RADD-702): `<space>/<page>`,
 *  where either segment may be a slug OR an id — which is what lets a pre-702
 *  UUID link resolve so the view can redirect it to the canonical slug URL. */
export const pageByPathQuery = (spaceSlug: string, pageSlug: string) =>
  queryOptions({
    queryKey: queryKeys.pageByPath(spaceSlug, pageSlug),
    meta: entityMeta(Entity.page),
    queryFn: () =>
      api.get<Page>(`${ApiPath.pages}/by-path/${encodeURIComponent(spaceSlug)}/${encodeURIComponent(pageSlug)}`),
    retry: false,
  });

/** Version history metadata (newest first). */
export const pageVersionsQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.pageVersions(pageId),
    meta: entityMeta(Entity.page),
    queryFn: () => api.get<PageVersionMeta[]>(apiPageVersionsPath(pageId)),
  });

/** One version's full content (the history viewer). */
export const pageVersionQuery = (pageId: string, version: number) =>
  queryOptions({
    queryKey: queryKeys.pageVersion(pageId, version),
    queryFn: () => api.get<DocVersion>(apiPageVersionPath(pageId, version)),
    staleTime: Infinity, // versions are immutable
  });

/** Issues linked to a page, hydrated (key/title/state), RBAC-filtered. */
export const pageItemsQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.pageItems(pageId),
    meta: entityMeta(Entity.page, Entity.item),
    queryFn: () => api.get<PageLinkedItem[]>(apiPageItemsPath(pageId)),
  });

/** Pages linked to an issue — the issue page's Pages row. */
export const itemPagesQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemPages(itemId),
    meta: entityMeta(Entity.page),
    queryFn: () => api.get<ItemPageRef[]>(apiItemDocsPath(itemId)),
    retry: false,
  });

/** Doc FTS for the palette's "Pages" section + any search box. */
export const pageSearchQuery = (q: string, limit: number) =>
  queryOptions({
    queryKey: queryKeys.docsSearch(q),
    meta: entityMeta(Entity.page),
    queryFn: () =>
      api.get<PageSearchResponse>(ApiPath.docsSearch, {
        query: { q, limit: String(limit) },
      }),
    placeholderData: keepPreviousData,
    enabled: q.trim().length > 0,
  });
