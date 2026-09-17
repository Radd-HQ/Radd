import { combineQueryWithFilters, splitQueryOrder } from "./slq";
import { BACKLOG_KEY, groupItemsForView, type ViewGroup } from "./view-utils";
import type { Cycle, Item, View } from "./types";

export const RESCHEDULING_KEY = "__rescheduling__";
export type BacklogOrder = "priority" | "recent" | "manual";
export interface PlanningOptions {
  showCompleted: boolean;
  backlogOrder: BacklogOrder;
  search: string;
  history: boolean;
  historyCycle: string;
}
export const DEFAULT_PLANNING: PlanningOptions = {
  showCompleted: true, backlogOrder: "priority", search: "", history: false, historyCycle: "",
};
const OPEN = "category NOT IN (done, canceled)";

/** Partition BEFORE paging. Sprint rank and backlog ordering are independent. */
export function planningQueries(view: View | undefined, cycles: Cycle[] | undefined, options = DEFAULT_PLANNING) {
  const all = groupItemsForView([], "cycle", { cycles, cycleFilter: view?.cycle_filter, includeCompletedCycles: true });
  const scheduled = all.filter(g => g.cycleId && g.cycleMeta?.status !== "completed");
  const historyCycles = all.filter(g => g.cycleMeta?.status === "completed")
    .sort((a,b) => (b.cycleMeta?.end ?? "").localeCompare(a.cycleMeta?.end ?? "") || b.label.localeCompare(a.label));
  const hidden = new Set(view?.hidden_columns ?? []);
  const ids = scheduled.filter(g => !hidden.has(g.key)).map(g => g.cycleId!);
  const where = splitQueryOrder(view?.query ?? "").where;
  const withQuery = (filters: string[], order: string, cycleIds?: string[]) => {
    if (!view) return undefined;
    const query = combineQueryWithFilters(where, filters) + ` ORDER BY ${order}`;
    const params = new URLSearchParams(view.query_string);
    params.set("q", query.trim());
    // Existing structured filters remain constraints; intersect cycle scopes.
    if (cycleIds) {
      const existing = params.getAll("cycle_id");
      params.delete("cycle_id");
      const scoped = existing.length ? cycleIds.filter(id => existing.includes(id)) : cycleIds;
      for (const id of scoped.length ? scoped : ["00000000-0000-0000-0000-000000000000"]) params.append("cycle_id", id);
    }
    return { ...view, query: query.trim(), query_string: params.toString() };
  };
  const backlogOrder = options.backlogOrder === "manual" ? "rank" : options.backlogOrder === "recent"
    ? "updated DESC, number DESC" : "priority DESC, updated DESC, number DESC";
  const sprintFilter = options.showCompleted ? [`(${OPEN} OR cycle.status = active)`] : [OPEN];
  const historyId = historyCycles.some(g => g.cycleId === options.historyCycle) ? options.historyCycle : historyCycles[0]?.cycleId;
  return {
    scheduled, historyCycles, cycleCount: ids.length,
    hiddenCount: scheduled.filter(g => hidden.has(g.key)).length,
    backlog: withQuery(["cycle IS EMPTY", OPEN, ...(options.search.trim() ? [`title ~ ${JSON.stringify(options.search.trim())}`] : [])], backlogOrder),
    sprints: withQuery(sprintFilter, "rank", ids),
    sprintOpen: withQuery([OPEN], "rank", ids),
    recovery: withQuery(["cycle.status = completed", OPEN], "priority DESC, updated DESC, number DESC",
      view?.cycle_filter ? historyCycles.map(g => g.cycleId!) : undefined),
    history: withQuery(["cycle.status = completed", "category IN (done, canceled)"], "rank", historyId ? [historyId] : []),
    historyId,
  };
}

/** Dedicated scheduling sections. Historical open work never masquerades as backlog. */
export function planningGroups(
  plan: ReturnType<typeof planningQueries>, sprint: Item[], recovery: Item[], backlog: Item[], history: Item[],
  cycles: Cycle[] | undefined, options: PlanningOptions, filtered: boolean,
  recoveryTotal?: number, backlogTotal?: number, historyTotal?: number, loadingMore = false,
): ViewGroup[] {
  const empty = filtered ? "No issues match the view’s filters. Adjust the filters to check for scheduled work."
    : "No issues scheduled. Move work here from the backlog or Needs rescheduling.";
  const groups = groupItemsForView(sprint, "cycle", { cycles }).filter(g => plan.scheduled.some(s => s.key === g.key))
    .map(g => ({...g, emptyMessage: loadingMore ? "No issues loaded here yet. More sprint work is available; use Load more if loading has paused." : empty, detail: "Manual issue order"}));
  groups.push({key: RESCHEDULING_KEY, label: "Needs rescheduling", items: recovery, total: recoveryTotal,
    dropDisabled: true, reorderDisabled: true, showSourceCycle: true,
    detail: "Open issues in completed sprints — move them to a live sprint or the backlog.",
    emptyMessage: filtered ? "No unfinished issues from completed sprints match these filters." : "No unfinished work left in completed sprints."});
  groups.push({key: BACKLOG_KEY, label: "Backlog", items: backlog, total: backlogTotal,
    reorderDisabled: options.backlogOrder !== "manual", detail: "Open, unscheduled work",
    emptyMessage: filtered || options.search.trim() ? "No backlog issues match your search or filters." : "No open, unscheduled issues."});
  if (options.history && plan.historyId) {
    const selected = plan.historyCycles.find(g => g.cycleId === plan.historyId);
    groups.push({key: `history:${plan.historyId}`, label: `History · ${selected?.label ?? "Completed sprint"}`,
      items: history, total: historyTotal, dropDisabled: true, dragDisabled: true, reorderDisabled: true,
      detail: "Completed work; unfinished issues appear in Needs rescheduling.",
      emptyMessage: "No completed issues match this view’s filters in this sprint."});
  }
  return groups;
}
