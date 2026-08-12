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
} from "../constants";
import { queryKeys } from "./shared";
import type {
  Attachment,
  AttachmentTarget,
  Comment,
  Item,
  ValidationContext,
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

/** Files attached to a parent — item or page (spec 29; polymorphic). */
export const attachmentsQuery = (target: AttachmentTarget) =>
  queryOptions({
    queryKey: queryKeys.attachments(target.entityType, target.entityId),
    queryFn: () =>
      api.get<Attachment[]>(apiAttachmentsPath(), {
        query: { entity_type: target.entityType, entity_id: target.entityId },
      }),
    meta: entityMeta(Entity.attachment),
  });

/**
 * One item's DIRECT children (RADD-655): an epic's issues, or an issue's
 * subtasks. Scoped by the same RBAC every other item read uses — the filter is
 * `parent_id`, which the items list already supports.
 */
export const childItemsQuery = (parentId: string) =>
  queryOptions({
    queryKey: queryKeys.childItems(parentId),
    meta: entityMeta(Entity.item),
    queryFn: () => api.get<Item[]>(ApiPath.items, { query: { parent_id: parentId } }),
  });

/**
 * Whether intake validation governs a draft with this shape (spec 119) — and
 * how hard, which is what decides whether "create anyway" is on offer.
 *
 * Re-queried on TYPE change, because a project may validate only its Bug type,
 * and a button that kept saying "Create" after someone switched to it would be
 * lying about what pressing it does. Cheap and cached: it resolves an index, no
 * graph is walked.
 */
export const validationContextQuery = (
  projectId: string | undefined,
  typeId?: string | null,
  formId?: string | null,
) =>
  queryOptions({
    queryKey: queryKeys.validationContext(projectId ?? "", typeId ?? null, formId ?? null),
    queryFn: () =>
      api.get<ValidationContext>(ApiPath.itemsValidateContext, {
        query: {
          project_id: projectId ?? "",
          type_id: typeId || undefined,
          form_id: formId || undefined,
        },
      }),
    enabled: Boolean(projectId),
    staleTime: 60_000,
    // A 403 (no `item.create` here) is a legitimate answer, not something to
    // retry: the caller reads a failed context as "ungoverned", which degrades
    // to the plain Create button rather than to a broken form.
    retry: false,
  });
