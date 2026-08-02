/** Approval requests and request participants (specs 71/72). */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiItemApprovalsPath,
  apiItemParticipantsPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  ItemApprovals,
  ItemParticipants,
  PendingApproval,
} from "../types";

/**
 * The item's approval requests + requestable targets (spec 71) — empty-quiet:
 * the server always 200s with empty lists, so the rail card simply doesn't
 * render for ungated items. Tagged `item` + `transition`: approval events ride
 * the item entity in realtime, and rule edits change what's requestable.
 */
export const itemApprovalsQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemApprovals(itemId),
    queryFn: () => api.get<ItemApprovals>(apiItemApprovalsPath(itemId)),
    meta: entityMeta(Entity.item, Entity.transition),
  });

/** Requests awaiting MY verdict (spec 71) — the My Work card. */
export const pendingApprovalsQuery = queryOptions({
  queryKey: queryKeys.pendingApprovals,
  queryFn: () => api.get<PendingApproval[]>(ApiPath.approvalsPending),
  meta: entityMeta(Entity.item),
});

/**
 * The item's participants (spec 72) — users + whole teams the item is shared
 * with; `can_manage` is server-computed per actor (item.update OR the item's
 * reporter). Tagged `item`: participant events ride the item entity in
 * realtime, so live invalidation is free.
 */
export const participantsQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemParticipants(itemId),
    queryFn: () => api.get<ItemParticipants>(apiItemParticipantsPath(itemId)),
    meta: entityMeta(Entity.item),
  });
