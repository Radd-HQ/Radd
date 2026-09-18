import { useEffect } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { Entity, invalidateEntities, type EntityTag } from "./cache";
import { itemInterests } from "./item-interests";
import type { Item } from "./types";
import {
  REALTIME_COALESCE_MS,
  REALTIME_RECONNECT_BASE_MS,
  REALTIME_RECONNECT_MAX_MS,
  REALTIME_WS_PATH,
} from "./constants";

/**
 * Server entity strings (each module's *Entity enum) → the frontend cache tags
 * they invalidate. Some map to two: a comment/worklog/link change also touches
 * the item that embeds its count/list. Unknown strings are ignored — a future
 * module's events are inert until this map learns them.
 */
const SERVER_ENTITY_TAGS: Record<string, EntityTag[]> = {
  item: [Entity.item],
  item_link: [Entity.item],
  comment: [Entity.comment, Entity.item],
  cycle: [Entity.cycle, Entity.item],
  cycle_series: [Entity.cycleSeries],
  release: [Entity.release, Entity.item],
  view: [Entity.view],
  label: [Entity.label, Entity.item],
  state: [Entity.project, Entity.item],
  // Transition config changes shift which state moves are allowed per item.
  workflow_transition: [Entity.transition, Entity.item],
  field: [Entity.field],
  access_grant: [Entity.accessGrant, Entity.field, Entity.attachment, Entity.page, Entity.view, Entity.dashboard],
  team: [Entity.team],
  group: [Entity.group],
  team_member: [Entity.team],
  role: [Entity.role],
  user: [Entity.member],
  project: [Entity.project],
  form: [Entity.form],
  automation_rule: [Entity.automation],
  worklog: [Entity.worklog, Entity.item],
  work_category: [Entity.workCategory],
  item_estimate: [Entity.worklog, Entity.item],
  web_link: [Entity.webLink, Entity.item],
  vcs_link: [Entity.vcsLink, Entity.item],
  notification: [Entity.notification],
  item_watcher: [Entity.watcher],
  attachment: [Entity.attachment, Entity.item],
  canned_response: [Entity.cannedResponse],
  sla_policy: [Entity.slaPolicy],
  // These keys are the SERVER's entity types — the broadcaster pushes
  // `event.entity_type` verbatim. RADD-701 renamed them to page_space/page and
  // these two were left behind, so nothing on a page ever refreshed (RADD-761).
  page_space: [Entity.docSpace],
  // A page change also touches its space's page_count in the spaces index.
  page: [Entity.page, Entity.docSpace],
  dashboard: [Entity.dashboard],
};

const ALL_TAGS = Object.values(Entity);
const activeStops = new Set<() => void>();

export function stopAllRealtime() {
  for (const stop of [...activeStops]) stop();
}

interface RealtimeMessage {
  entity?: string;
  queries?: string[];
}

function wsUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${REALTIME_WS_PATH}`;
}

/**
 * One live socket per app shell (spec 27). Incoming entity signals are
 * coalesced for a beat, then flushed as a single invalidateEntities() — every
 * query tagged with those entities refetches, so boards/issues/inbox go live
 * with no per-view code. On (re)connect everything is invalidated once to
 * cover whatever was missed while disconnected.
 */
export function startRealtime(queryClient: QueryClient): () => void {
  let socket: WebSocket | null = null;
  let closed = false;
  let attempts = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let flushTimer: ReturnType<typeof setTimeout> | undefined;
  let subscriptionTimer: ReturnType<typeof setTimeout> | undefined;
  let lastSubscriptions = "";
  const pending = new Set<EntityTag>();
  const pendingQueries = new Set<string>();

  const subscribe = () => {
    subscriptionTimer = undefined;
    if (closed || socket?.readyState !== WebSocket.OPEN) return;
    const queries = queryClient.getQueryCache().getAll().filter(query => query.isActive()).flatMap(query => {
      const meta = query.meta as {entities?: EntityTag[]; projectId?: string; itemId?: string; itemDetail?: boolean} | undefined;
      if (!meta?.entities?.length || query.queryHash.length > 4096) return [];
      const entities = Object.entries(SERVER_ENTITY_TAGS).filter(([, tags]) => tags.some(tag => meta.entities!.includes(tag))).map(([entity]) => entity);
      const itemIds = meta.itemDetail ? itemInterests(query.state.data as Item | undefined)
        : meta.itemId ? [meta.itemId] : undefined;
      return entities.length ? [{id: query.queryHash, entities, project_id: meta.projectId ?? null,
        item_ids: itemIds ?? null}] : [];
    });
    // A rare oversized plugin surface uses the legacy coarse subscription.
    let payload = JSON.stringify({queries: queries.length > 128 ? null : queries});
    if (payload.length > 262144) payload = JSON.stringify({queries: null});
    if (payload !== lastSubscriptions) {
      socket.send(payload);
      lastSubscriptions = payload;
    }
  };
  const unsubscribeCache = queryClient.getQueryCache().subscribe(() => {
    if (!closed) subscriptionTimer ??= setTimeout(subscribe, REALTIME_COALESCE_MS);
  });

  const flush = () => {
    flushTimer = undefined;
    if (pending.size === 0 && pendingQueries.size === 0) return;
    const tags = [...pending];
    pending.clear();
    const hashes = new Set(pendingQueries);
    pendingQueries.clear();
    if (tags.length) void invalidateEntities(queryClient, ...tags);
    if (hashes.size) void queryClient.invalidateQueries({predicate: query => hashes.has(query.queryHash)});
  };

  const queue = (tags: EntityTag[]) => {
    for (const tag of tags) pending.add(tag);
    flushTimer ??= setTimeout(flush, REALTIME_COALESCE_MS);
  };

  const connect = () => {
    if (closed) return;
    socket = new WebSocket(wsUrl());

    socket.onopen = () => {
      if (closed) return;
      lastSubscriptions = "";
      subscribe();
      const firstConnect = attempts === 0;
      attempts = 0;
      // Refetch the world we may have drifted from (skip the very first
      // connect — mount fetches are already in flight).
      if (!firstConnect) queue(ALL_TAGS);
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      if (closed) return;
      try {
        const message = JSON.parse(event.data) as RealtimeMessage;
        if (Array.isArray(message.queries)) {
          for (const hash of message.queries) pendingQueries.add(hash);
          flushTimer ??= setTimeout(flush, REALTIME_COALESCE_MS);
          return;
        }
        const tags = message.entity ? SERVER_ENTITY_TAGS[message.entity] : undefined;
        if (tags) queue(tags);
      } catch {
        // Malformed frame — ignore.
      }
    };

    socket.onclose = () => {
      socket = null;
      if (closed) return;
      const delay = Math.min(
        REALTIME_RECONNECT_BASE_MS * 2 ** attempts,
        REALTIME_RECONNECT_MAX_MS,
      );
      attempts += 1;
      reconnectTimer = setTimeout(connect, delay);
    };
  };

  connect();
  const stop = () => {
    closed = true;
    clearTimeout(reconnectTimer);
    clearTimeout(flushTimer);
    clearTimeout(subscriptionTimer);
    unsubscribeCache();
    socket?.close();
    activeStops.delete(stop);
  };
  activeStops.add(stop);
  return stop;
}

/** Mount-once hook for the app shell. */
export function useRealtime() {
  const queryClient = useQueryClient();
  useEffect(() => startRealtime(queryClient), [queryClient]);
}
