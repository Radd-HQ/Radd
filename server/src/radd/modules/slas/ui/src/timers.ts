import { queryOptions } from "@tanstack/react-query";
import { api, type ItemAttributeBatchArgs, type QuerySource } from "@radd/plugin-sdk";

/** The timer endpoints this plugin serves (`slas/router.py`). */
const SLA_BATCH_PATH = "/items/sla/batch";
const itemSlaPath = (itemId: string) => `/items/${itemId}/sla`;

/** Timers tick server-side — re-read a visible countdown every minute (spec 63). */
const SLA_REFETCH_MS = 60_000;

/** Timer reads go stale with an item change or a policy edit: `sla_policy` is the server's own
 *  entity type, declared verbatim so realtime policy events reach it (RADD-1396). */
const TIMER_META = { entities: ["item", "sla_policy"] };

/** Mirror of `slas.types.SlaKind`. */
export const SlaKind = { response: "response", resolution: "resolution" } as const;
type SlaKindValue = (typeof SlaKind)[keyof typeof SlaKind];

/** The facts every timer chip renders from. */
export interface TimerState {
  met_at: string | null;
  breached: boolean;
  paused: boolean;
  remaining_seconds: number | null;
}

/** One timer of an item's MATCHED policy, as the batch endpoint returns it (spec 63). */
export interface SlaBatchTimer extends TimerState {
  policy_name: string;
  kind: SlaKindValue;
  due_at: string | null;
}

/** POST /items/sla/batch — readable items with a matched policy only. */
type SlaBatchResponse = Record<string, SlaBatchTimer[]>;

/** GET /items/{id}/sla — the matched policy's timers, live (at most one entry since spec 63). */
interface ItemSla {
  entries: {
    policy_id: string;
    policy_name: string;
    timers: (TimerState & { kind: SlaKindValue; target_minutes: number; due_at: string | null })[];
  }[];
}

/** The `slas.timers` query source: the SLA column's and card cell's batch. The host asks it once
 * per page of rows (≤200 ids — the endpoint's own cap) and shares the result between surfaces. */
export const timersSource: QuerySource<SlaBatchResponse> = {
  key: "slas.timers",
  meta: TIMER_META,
  refetchInterval: SLA_REFETCH_MS,
  fetch: (args, signal) =>
    api.post<SlaBatchResponse>(SLA_BATCH_PATH, { item_ids: (args as ItemAttributeBatchArgs).ids }, { signal }),
};

/** One item's timers for the issue rail; keyed under the plugin's name, so disabling slas drops it. */
export const itemSlaQuery = (itemId: string) =>
  queryOptions({
    queryKey: ["slas", "item", itemId] as const,
    queryFn: ({ signal }) => api.get<ItemSla>(itemSlaPath(itemId), { signal }),
    meta: TIMER_META,
    refetchInterval: SLA_REFETCH_MS,
  });
