import { useEffect, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { useDebounced } from "./hooks";
import { pagedViewItemsQuery } from "./queries/views";
import { planningCountQuery } from "./usePlanningSprints";
import { combineQueryWithFilters, splitQueryOrder } from "./slq";
import { RESCHEDULING_KEY, type planningQueries } from "./planning-query";
import { BACKLOG_KEY, type ViewGroup } from "./view-utils";
import type { Item, View } from "./types";

/** Section filters search the server result, never only the already-loaded rows. */
export function usePlanningSectionSearch(plan: ReturnType<typeof planningQueries>, enabled: boolean, scope: string, showHistory: boolean) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [pages, setPages] = useState<Record<string, number>>({});
  useEffect(() => { setDrafts({}); setPages({}); }, [scope]);
  const settled = useDebounced(drafts, 250);
  const sources: Record<string, View | undefined> = {
    [BACKLOG_KEY]: plan.backlog, [RESCHEDULING_KEY]: plan.recovery,
  };
  for (const group of plan.scheduled) {
    if (!plan.sprints) continue;
    const params = new URLSearchParams(plan.sprints.query_string);
    if (!params.getAll("cycle_id").includes(group.key)) continue;
    params.delete("cycle_id"); params.append("cycle_id", group.key);
    sources[group.key] = {...plan.sprints, query_string: params.toString()};
  }
  if (showHistory && plan.historyId) sources[`history:${plan.historyId}`] = plan.history;
  const searches = Object.entries(settled).flatMap(([key, text]) => {
    const source = sources[key];
    if (!enabled || !source || !text.trim()) return [];
    const {where, order} = splitQueryOrder(source.query);
    const query = combineQueryWithFilters(where, [`title ~ ${JSON.stringify(text.trim())}`]) + (order ? ` ${order}` : "");
    const params = new URLSearchParams(source.query_string); params.set("q", query);
    return [{key, view: {...source, query, query_string: params.toString()}, pages: pages[key] ?? 1}];
  });
  const requests = searches.flatMap(search => Array.from({length: search.pages}, (_, i) => ({...search, page: i + 1})));
  const rows = useQueries({queries: requests.map(r => ({...pagedViewItemsQuery(r.view, r.page, 200), placeholderData: undefined}))});
  const counts = useQueries({queries: searches.map(r => planningCountQuery(r.view))});
  const matches = new Map<string, Item[]>();
  requests.forEach((r, i) => matches.set(r.key, [...(matches.get(r.key) ?? []), ...(rows[i].data ?? [])]));
  const control = (group: ViewGroup) => {
    const index = searches.findIndex(s => s.key === group.key);
    const indices = requests.flatMap((r, i) => r.key === group.key ? [i] : []);
    const filtered = Boolean(drafts[group.key]?.trim());
    const pending = drafts[group.key] !== settled[group.key] || indices.some(i => rows[i].isFetching);
    const count = counts[index];
    const error = indices.some(i => rows[i].isError) || Boolean(count?.isError);
    const loaded = matches.get(group.key)?.length ?? 0;
    return {
      value: drafts[group.key] ?? "", filtered, pending, error,
      total: count?.data?.total, loaded,
      more: index >= 0 && !pending && !error && (count?.data ? loaded < count.data.total : indices.length > 0 && rows[indices.at(-1)!].data?.length === 200),
      onChange: (value: string) => { setDrafts(d => ({...d, [group.key]: value})); setPages(p => ({...p, [group.key]: 1})); },
      onMore: () => setPages(p => ({...p, [group.key]: (p[group.key] ?? 1) + 1})),
      onRetry: () => { indices.forEach(i => void rows[i].refetch()); void count?.refetch(); },
    };
  };
  return {
    control,
    signature: JSON.stringify(drafts),
    backlogFiltered: Boolean(drafts[BACKLOG_KEY]?.trim()),
    displayItems: (groups: {key: string; items: Item[]}[]) => groups.flatMap(group => drafts[group.key]?.trim()
      ? drafts[group.key] === settled[group.key] ? matches.get(group.key) ?? [] : []
      : group.items),
    apply: (groups: ViewGroup[]) => groups.map(group => {
      if (!drafts[group.key]?.trim()) return group;
      const state = control(group);
      return {...group, items: drafts[group.key] === settled[group.key] ? matches.get(group.key) ?? [] : [],
        reorderDisabled: true,
        emptyMessage: state.pending ? "Searching this section…" : state.error ? "Could not search this section. Retry below." : "No issue titles match this section’s filter."};
    }),
  };
}
export type SectionSearchControl = ReturnType<ReturnType<typeof usePlanningSectionSearch>["control"]>;
