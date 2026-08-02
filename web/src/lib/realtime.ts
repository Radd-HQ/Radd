import { useEffect } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { Entity, invalidateEntities, type EntityTag } from "./cache";
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
  release: [Entity.release, Entity.item],
  view: [Entity.view],
  label: [Entity.label, Entity.item],
  state: [Entity.project, Entity.item],
  // Transition config changes shift which state moves are allowed per item.
  workflow_transition: [Entity.transition, Entity.item],
  field: [Entity.field],
  team: [Entity.team],
  team_member: [Entity.team],
  project_team: [Entity.team, Entity.project],
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
  doc_space: [Entity.docSpace],
  // A page change also touches its space's page_count in the spaces index.
  doc_page: [Entity.page, Entity.docSpace],
  dashboard: [Entity.dashboard],
};

const ALL_TAGS = Object.values(Entity);

interface RealtimeMessage {
  entity?: string;
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
  const pending = new Set<EntityTag>();

  const flush = () => {
    flushTimer = undefined;
    if (pending.size === 0) return;
    const tags = [...pending];
    pending.clear();
    void invalidateEntities(queryClient, ...tags);
  };

  const queue = (tags: EntityTag[]) => {
    for (const tag of tags) pending.add(tag);
    flushTimer ??= setTimeout(flush, REALTIME_COALESCE_MS);
  };

  const connect = () => {
    if (closed) return;
    socket = new WebSocket(wsUrl());

    socket.onopen = () => {
      const firstConnect = attempts === 0;
      attempts = 0;
      // Refetch the world we may have drifted from (skip the very first
      // connect — mount fetches are already in flight).
      if (!firstConnect) queue(ALL_TAGS);
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        const message = JSON.parse(event.data) as RealtimeMessage;
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
  return () => {
    closed = true;
    clearTimeout(reconnectTimer);
    clearTimeout(flushTimer);
    socket?.close();
  };
}

/** Mount-once hook for the app shell. */
export function useRealtime() {
  const queryClient = useQueryClient();
  useEffect(() => startRealtime(queryClient), [queryClient]);
}
