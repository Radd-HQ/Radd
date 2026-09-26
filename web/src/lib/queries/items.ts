/** Items (paged/infinite/by-key), comments, and attachments. */

import { commentFeedQuery, CommentSection } from "./comment-feed";
import { queryOptions } from "@tanstack/react-query";
import { api, type CursorPage } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiAttachmentsPath,
  apiItemByKeyPath,
  apiItemCommentsPath,
} from "../constants";
import { queryKeys } from "./shared";
import type { Attachment, AttachmentTarget, Item } from "../types";
import type { ValidationContext } from "@radd-plugin-ui/automations/types";

/**
 * Resolve an item by its canonical key (`TD-25`) via the server's by-key
 * resolver (spec 21) — the single source for the key-addressed issue page.
 * `retry: false` so an unknown key's 404 surfaces immediately as "not found".
 */
export const itemByKeyQuery = (key: string) =>
  queryOptions({
    queryKey: queryKeys.itemByKey(key),
    meta: { ...entityMeta(Entity.item, Entity.project, Entity.role, Entity.team,
      Entity.group, Entity.member, Entity.field, Entity.accessGrant), itemDetail: true },
    queryFn: ({ signal }) => api.get<Item>(apiItemByKeyPath(key), { signal }),
    retry: false,
  });

/** Files attached to a parent — item or page (spec 29; polymorphic). */
export const attachmentsQuery = (target: AttachmentTarget) =>
  queryOptions({
    queryKey: queryKeys.attachments(target.entityType, target.entityId),
    queryFn: ({ signal }) =>
      api.get<Attachment[]>(apiAttachmentsPath(), {
        signal,
        query: { entity_type: target.entityType, entity_id: target.entityId },
      }),
    meta: entityMeta(Entity.attachment),
  });

/** Whether (and how hard) intake validation governs a draft of this shape — what decides whether
 *  "create anyway" is offered. Keyed on TYPE, since a project may validate only its Bug type. */
export const validationContextQuery = (
  projectId: string | undefined,
  typeId?: string | null,
  formId?: string | null,
) =>
  queryOptions({
    queryKey: queryKeys.validationContext(projectId ?? "", typeId ?? null, formId ?? null),
    queryFn: ({ signal }) =>
      api.get<ValidationContext>(ApiPath.itemsValidateContext, {
        signal,
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

export const itemCommentFeedQuery = (itemId: string, unresolvedOnly = false, through?: string) =>
  commentFeedQuery(queryKeys.comments(itemId), apiItemCommentsPath(itemId), CommentSection.all, unresolvedOnly, through);

/** An item's DIRECT children (an epic's issues, an issue's subtasks), cursor-paged. */
export const childItemPagesQuery = (parentId: string) => ({
  queryKey: ["child-item-cursors", parentId],
  meta: entityMeta(Entity.item),
  initialPageParam: null as string | null,
  queryFn: ({ signal, pageParam }: {signal: AbortSignal; pageParam: string | null}) =>
    api.getCursor<Item>(ApiPath.items, {signal, query: {parent_id: parentId,
      q: "ORDER BY category ASC, number ASC", limit: "50", after: pageParam ?? undefined}}),
  getNextPageParam: (last: CursorPage<Item>) => last.next ?? undefined,
});
