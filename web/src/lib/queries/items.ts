/** Items (paged/infinite/by-key), comments, and attachments. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  ITEMS_PAGE_LIMIT,
  apiAttachmentsPath,
  apiItemByKeyPath,
  apiItemCommentsPath,
  apiItemPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  Attachment,
  AttachmentTarget,
  Comment,
  Item,
} from "../types";

/** All items of a project, one page at the API cap (pagination: known gap). */
export const itemsQuery = (projectId: string, archived = false) =>
  queryOptions({
    queryKey: queryKeys.items(projectId, archived),
    // `meta.entities` = which entities this query caches; item mutations
    // invalidate by entity, so this refreshes live (see lib/cache.ts).
    meta: entityMeta(Entity.item),
    queryFn: () =>
      api.get<Item[]>(ApiPath.items, {
        query: {
          project_id: projectId,
          archived: archived ? "true" : undefined,
          limit: String(ITEMS_PAGE_LIMIT),
        },
      }),
  });

/**
 * Infinite variant for the project List page (spec 41): pages of the API cap,
 * `getNextPageParam` = next offset while pages come back full.
 */
export const infiniteItemsQuery = (projectId: string, archived = false) => ({
  queryKey: queryKeys.itemsInfinite(projectId, archived),
  meta: entityMeta(Entity.item),
  initialPageParam: 0,
  queryFn: ({ pageParam }: { pageParam: number }) =>
    api.get<Item[]>(ApiPath.items, {
      query: {
        project_id: projectId,
        archived: archived ? "true" : undefined,
        limit: String(ITEMS_PAGE_LIMIT),
        offset: String(pageParam),
      },
    }),
  getNextPageParam: (lastPage: Item[], _all: Item[][], lastOffset: number) =>
    lastPage.length === ITEMS_PAGE_LIMIT ? lastOffset + ITEMS_PAGE_LIMIT : undefined,
});

export const itemQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.item(itemId),
    meta: entityMeta(Entity.item),
    queryFn: () => api.get<Item>(apiItemPath(itemId)),
  });

/**
 * Resolve an item by its canonical key (`TD-25`) via the server's by-key
 * resolver (spec 21) — the single source for the key-addressed issue page.
 * `retry: false` so an unknown key's 404 surfaces immediately as "not found".
 */
export const itemByKeyQuery = (key: string) =>
  queryOptions({
    queryKey: queryKeys.itemByKey(key),
    meta: entityMeta(Entity.item),
    queryFn: () => api.get<Item>(apiItemByKeyPath(key)),
    retry: false,
  });

/**
 * Comments for an item. The comments module may not be deployed yet (spec 02
 * lands in parallel) — the thread component feature-detects the 404.
 */
export const commentsQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.comments(itemId),
    queryFn: () => api.get<Comment[]>(apiItemCommentsPath(itemId)),
    retry: false,
  });

/** Files attached to a parent — item or doc page (spec 29; polymorphic). */
export const attachmentsQuery = (target: AttachmentTarget) =>
  queryOptions({
    queryKey: queryKeys.attachments(target.entityType, target.entityId),
    queryFn: () =>
      api.get<Attachment[]>(apiAttachmentsPath(), {
        query: { entity_type: target.entityType, entity_id: target.entityId },
      }),
    meta: entityMeta(Entity.attachment),
  });
