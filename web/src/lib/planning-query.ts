import { combineQueryWithFilters } from "./slq";
import { groupItemsForView } from "./view-utils";
import type { Cycle, View } from "./types";

/** Planning partitions BEFORE paging, using exactly the cycles its headers show. */
export function planningQueries(view: View | undefined, cycles: Cycle[] | undefined) {
  if (!view) return { backlog: undefined, sprints: undefined, cycleCount: 0 };
  const hidden = new Set(view.hidden_columns ?? []);
  const ids = groupItemsForView([], "cycle", { cycles, cycleFilter: view.cycle_filter })
    .filter(group => group.cycleId && !hidden.has(group.key)).map(group => group.cycleId!);
  const ordered = /\border\s+by\b/i.test(view.query)
    ? view.query : `${view.query} ORDER BY category ASC, priority DESC, updated DESC, number ASC`.trim();
  const withQuery = (query: string, cycleIds?: string[]) => {
    const params = new URLSearchParams(view.query_string);
    params.set("q", query);
    // Keep any existing scope constraints; these are additional cycle constraints.
    if (cycleIds) for (const id of cycleIds) params.append("cycle_id", id);
    return { ...view, query, query_string: params.toString() };
  };
  return {
    backlog: withQuery(combineQueryWithFilters(ordered, ["cycle IS EMPTY", "category NOT IN (done, canceled)"])),
    sprints: withQuery(ordered, ids),
    cycleCount: ids.length,
  };
}
