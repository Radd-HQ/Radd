/** Wiki (docs module — spec 43). */

import { keepPreviousData, queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiDocPageItemsPath,
  apiDocPagePath,
  apiDocPageVersionPath,
  apiDocPageVersionsPath,
  apiDocSpacePagesPath,
  apiItemDocsPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  DocLinkedItem,
  DocPage,
  DocPageSummary,
  DocSearchResponse,
  DocSpace,
  DocVersion,
  DocVersionMeta,
  ItemDocRef,
} from "../types";

// ---------------------------------------------------------------------------
// Wiki (docs module — spec 43)
// ---------------------------------------------------------------------------

/** All doc spaces with live page counts (any member: doc.read). */
export const docSpacesQuery = () =>
  queryOptions({
    queryKey: queryKeys.docSpaces,
    meta: entityMeta(Entity.docSpace),
    queryFn: () => api.get<DocSpace[]>(ApiPath.docSpaces),
  });

/** A space's flat page rows — the tree component assembles the hierarchy. */
export const docPagesQuery = (spaceId: string) =>
  queryOptions({
    queryKey: queryKeys.docPages(spaceId),
    meta: entityMeta(Entity.docPage),
    queryFn: () => api.get<DocPageSummary[]>(apiDocSpacePagesPath(spaceId)),
  });

/** Full page: body + space + breadcrumb (the canonical page view). */
export const docPageQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.docPage(pageId),
    meta: entityMeta(Entity.docPage),
    queryFn: () => api.get<DocPage>(apiDocPagePath(pageId)),
    retry: false,
  });

/** Version history metadata (newest first). */
export const docPageVersionsQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.docPageVersions(pageId),
    meta: entityMeta(Entity.docPage),
    queryFn: () => api.get<DocVersionMeta[]>(apiDocPageVersionsPath(pageId)),
  });

/** One version's full content (the history viewer). */
export const docPageVersionQuery = (pageId: string, version: number) =>
  queryOptions({
    queryKey: queryKeys.docPageVersion(pageId, version),
    queryFn: () => api.get<DocVersion>(apiDocPageVersionPath(pageId, version)),
    staleTime: Infinity, // versions are immutable
  });

/** Issues linked to a page, hydrated (key/title/state), RBAC-filtered. */
export const docPageItemsQuery = (pageId: string) =>
  queryOptions({
    queryKey: queryKeys.docPageItems(pageId),
    meta: entityMeta(Entity.docPage, Entity.item),
    queryFn: () => api.get<DocLinkedItem[]>(apiDocPageItemsPath(pageId)),
  });

/** Pages linked to an issue — the issue page's Docs row. */
export const itemDocsQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemDocs(itemId),
    meta: entityMeta(Entity.docPage),
    queryFn: () => api.get<ItemDocRef[]>(apiItemDocsPath(itemId)),
    retry: false,
  });

/** Doc FTS for the palette's "Docs" section + any search box. */
export const docsSearchQuery = (q: string, limit: number) =>
  queryOptions({
    queryKey: queryKeys.docsSearch(q),
    meta: entityMeta(Entity.docPage),
    queryFn: () =>
      api.get<DocSearchResponse>(ApiPath.docsSearch, {
        query: { q, limit: String(limit) },
      }),
    placeholderData: keepPreviousData,
    enabled: q.trim().length > 0,
  });
