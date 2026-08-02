import { shortDate } from "./dates";
import { fieldInScope } from "./field-scope";
import {
  CATEGORY_META,
  CYCLE_STATUS_META,
  CYCLE_STATUS_ORDER,
  KIND_META,
  KIND_ORDER,
  PRIORITY_META,
  PRIORITY_ORDER,
  VIEW_AXIS_LABELS,
  VIEW_AXIS_ORDER,
} from "./meta";
import {
  CF_AXIS_PREFIX,
  CycleStatus,
  FieldType,
  ItemKind,
  StateCategory,
  ViewAxis,
  type AxisToken,
  type Cycle,
  type CycleStatusValue,
  type FieldDef,
  type Item,
  type State,
} from "./types";

/**
 * Client-side bucketing for saved views (specs 09/11): the SERVER already
 * filtered AND ordered the items (SLQ `q=` incl. ORDER BY); bucketing along an
 * axis token (`state|assignee|priority|kind|team|cf.<key>`) is pure
 * presentation. Item order within a bucket is the server order — never re-sort.
 */

export interface ViewGroup {
  /** Stable bucket key (state/user/team/cycle id, enum member, option, or sentinel). */
  key: string;
  label: string;
  /** Column-header dot accent (state categories, cycle status); undefined = no dot. */
  dotClassName?: string;
  /** Optional sub-header line (cycle summary: "Active · Aug 1 – Aug 14 · 3/8 done"). */
  detail?: string;
  /** Optional progress fraction 0–1 for a thin bar (cycle groups: done/total). */
  progress?: number;
  /** Set on cycle-axis groups: the cycle's id, so headers can show the
   *  cycle-wide time stats (estimate/logged/remaining, same source as the
   *  cycle page). Absent on the Backlog bucket and every other axis. */
  cycleId?: string;
  /** Structured cycle-header facts (status/dates/done-count) so list handles
   *  can render them as pills; `detail` keeps the flat-text fallback. */
  cycleMeta?: {
    status: CycleStatusValue;
    start: string | null;
    end: string | null;
    done: number;
    total: number;
  };
  items: Item[];
}

/** Sentinel bucket keys for unset values (never collide with UUIDs/options).
 *  Exported so the drag-to-move planner (lib/axis-dnd.ts) can map a drop onto the
 *  "unset" bucket to a null field value. */
export const UNASSIGNED_KEY = "__unassigned__";
export const NO_TEAM_KEY = "__no_team__";
export const NO_VALUE_KEY = "__none__";
export const BACKLOG_KEY = "__backlog__";

export const UNASSIGNED_LABEL = "Unassigned";
export const NO_TEAM_LABEL = "No team";
export const NO_VALUE_LABEL = "None";
export const BACKLOG_LABEL = "Backlog";

/** Everything the axis groupers may need to resolve buckets. */
export interface AxisContext {
  /** The view's project's states (undefined for all-projects views). */
  states?: State[];
  /** Registry definitions in scope — resolves `cf.<key>` option buckets. */
  fields?: FieldDef[];
  /** All cycles — the `cycle` axis header set (incl. empty staging cycles). */
  cycles?: Cycle[];
  /** Optional cycle-name glob narrowing the `cycle` header set; null/'' = all. */
  cycleFilter?: string | null;
  /** Reveal COMPLETED cycles in the `cycle` header set. No surface sets this
   *  today — completed cycles are viewable ONLY on Settings → Cycles, by
   *  product decision — but the grouping stays parameterised rather than
   *  hard-coded so a future surface can opt in. Note it omits their ITEMS too
   *  (same semantics as `cycleFilter`: a cycle that isn't a header has nowhere
   *  to put them). */
  includeCompletedCycles?: boolean;
}

/**
 * Cycles a user can still move work INTO — everything except completed.
 * Completed cycles are viewable only on Settings → Cycles (product decision),
 * and a picker that offers them invites moving live work into a finished
 * sprint. Shared by the sidebar, the item context menu and bulk edit so the
 * three cannot drift.
 */
export function selectableCycles(cycles: Cycle[] | undefined): Cycle[] {
  return (cycles ?? []).filter((cycle) => cycle.status !== CycleStatus.completed);
}

/** True for a `cf.<key>` custom-field axis token. */
export function isCfAxis(axis: string): boolean {
  return axis.startsWith(CF_AXIS_PREFIX);
}

export const cfAxisToken = (fieldKey: string): AxisToken => `${CF_AXIS_PREFIX}${fieldKey}`;

/** Human label for an axis token: builtin label, or the cf field's name. */
export function axisLabel(axis: string, fields: FieldDef[] | undefined): string {
  if (isCfAxis(axis)) {
    const key = axis.slice(CF_AXIS_PREFIX.length);
    return (fields ?? []).find((field) => field.key === key)?.name ?? key;
  }
  return VIEW_AXIS_LABELS[axis as keyof typeof VIEW_AXIS_LABELS] ?? axis;
}

/**
 * Axis-picker options for a scope (spec 11): the builtin axes plus every
 * SELECT-type registry field visible in scope, token `cf.<key>`.
 */
export function axisOptions(
  fields: FieldDef[],
  projectId: string | null,
): { value: AxisToken; label: string }[] {
  const selectFields = fields.filter(
    (field) => field.type === FieldType.select && fieldInScope(field, projectId),
  );
  return [
    ...VIEW_AXIS_ORDER.map((axis) => ({ value: axis as AxisToken, label: VIEW_AXIS_LABELS[axis] })),
    ...selectFields.map((field) => ({ value: cfAxisToken(field.key), label: field.name })),
  ];
}

/**
 * Bucket `items` along an axis token. Unknown/stale tokens (e.g. a cf field
 * the registry no longer exposes) degrade to a single flat bucket rather than
 * dropping items.
 */
export function groupItemsForView(
  items: Item[],
  axis: AxisToken | string,
  context: AxisContext,
): ViewGroup[] {
  if (isCfAxis(axis)) {
    return groupByCustomField(items, axis.slice(CF_AXIS_PREFIX.length), context.fields);
  }
  switch (axis) {
    case ViewAxis.state:
      return groupByState(items, context.states);
    case ViewAxis.assignee:
      return groupByAssignee(items);
    case ViewAxis.team:
      return groupByTeam(items);
    case ViewAxis.priority:
      return PRIORITY_ORDER.map((priority) => ({
        key: priority,
        label: PRIORITY_META[priority].label,
        items: items.filter((item) => item.priority === priority),
      }));
    case ViewAxis.kind:
      return KIND_ORDER.map((kind) => ({
        key: kind,
        label: `${KIND_META[kind].label}s`,
        items: items.filter((item) => (item.kind ?? ItemKind.issue) === kind),
      }));
    case ViewAxis.cycle:
      return groupByCycle(
        items,
        context.cycles,
        context.cycleFilter,
        context.includeCompletedCycles ?? false,
      );
    default:
      return [{ key: axis, label: "All items", items }];
  }
}

/**
 * `cycle` buckets (spec 23): one section per cycle — the FULL cycle
 * list (so empty staging cycles appear), MINUS completed cycles unless the
 * surface asks for them, optionally narrowed by a name glob, ordered
 * active → upcoming → draft → completed then by start date. Items with
 * no cycle collect under a trailing **Backlog** bucket; items whose cycle is
 * filtered out are omitted (that is what the pattern means).
 */
function groupByCycle(
  items: Item[],
  cycles: Cycle[] | undefined,
  cycleFilter: string | null | undefined,
  includeCompleted: boolean,
): ViewGroup[] {
  const all = includeCompleted
    ? (cycles ?? [])
    : (cycles ?? []).filter((cycle) => cycle.status !== CycleStatus.completed);
  const shown = cycleFilter
    ? all.filter((cycle) => matchesCycleFilter(cycle.name, cycleFilter))
    : all;
  const groups: ViewGroup[] = [...shown].sort(compareCyclesForAxis).map((cycle) => {
    const bucket = items.filter((item) => item.cycle?.id === cycle.id);
    return {
      key: cycle.id,
      label: cycle.name,
      dotClassName: CYCLE_STATUS_META[cycle.status].dotClassName,
      detail: cycleDetail(cycle, bucket),
      progress: bucket.length ? doneCount(bucket) / bucket.length : undefined,
      cycleId: cycle.id,
      cycleMeta: {
        status: cycle.status,
        start: cycle.start_date,
        end: cycle.end_date,
        done: doneCount(bucket),
        total: bucket.length,
      },
      items: bucket,
    };
  });
  // Backlog is always present and rendered last, even when empty.
  groups.push({
    key: BACKLOG_KEY,
    label: BACKLOG_LABEL,
    items: items.filter((item) => !item.cycle),
  });
  return groups;
}

/** Items sitting in a done-category state — the "done" half of a cycle summary. */
function doneCount(items: Item[]): number {
  return items.filter((item) => item.state.category === StateCategory.done).length;
}

/** "Active · Aug 1 – Aug 14 · 3/8 done" (draft: "Draft · Not scheduled · 0/2 done"). */
function cycleDetail(cycle: Cycle, bucket: Item[]): string {
  const status = CYCLE_STATUS_META[cycle.status].label;
  const range =
    cycle.start_date && cycle.end_date
      ? `${shortDate(cycle.start_date)} – ${shortDate(cycle.end_date)}`
      : "Not scheduled";
  return `${status} · ${range} · ${doneCount(bucket)}/${bucket.length} done`;
}

/** Cycle-axis order: status rank (meta), then start date asc, dateless last by name. */
function compareCyclesForAxis(a: Cycle, b: Cycle): number {
  const rank = CYCLE_STATUS_ORDER.indexOf(a.status) - CYCLE_STATUS_ORDER.indexOf(b.status);
  if (rank !== 0) return rank;
  if (a.start_date && b.start_date && a.start_date !== b.start_date) {
    return a.start_date < b.start_date ? -1 : 1;
  }
  if (a.start_date && !b.start_date) return -1;
  if (!a.start_date && b.start_date) return 1;
  return a.name.localeCompare(b.name);
}

/**
 * Cycle-header filter (spec 56): the pattern is a REGEX — case-insensitive,
 * unanchored — so `PIPE` matches "PIPE - 116", `^TS - [0-9]$` pins single-digit
 * TS cycles, `PIPE|TS` shows both series. Blank = match all. The server 409s
 * invalid patterns on save; a stored-then-broken one degrades to match-all
 * rather than blanking the view.
 */
export function matchesCycleFilter(name: string, pattern: string): boolean {
  const trimmed = pattern.trim();
  if (!trimmed) return true;
  try {
    return new RegExp(trimmed, "i").test(name);
  } catch {
    return true;
  }
}

/**
 * `cf.<key>` buckets: the registry field's options in registry order, then any
 * stale values observed on items (options edited since), then always a
 * trailing "None" bucket for items lacking a value.
 */
function groupByCustomField(
  items: Item[],
  fieldKey: string,
  fields: FieldDef[] | undefined,
): ViewGroup[] {
  const definition = (fields ?? []).find((field) => field.key === fieldKey);
  const valueOf = (item: Item): string | null => {
    const value = item.custom_fields[fieldKey];
    return typeof value === "string" && value !== "" ? value : null;
  };
  const known = definition?.options ?? [];
  const stale = [...new Set(items.map(valueOf).filter((v): v is string => v !== null))]
    .filter((value) => !known.includes(value))
    .sort();
  return [
    ...[...known, ...stale].map((option) => ({
      key: option,
      label: option,
      items: items.filter((item) => valueOf(item) === option),
    })),
    {
      key: NO_VALUE_KEY,
      label: NO_VALUE_LABEL,
      items: items.filter((item) => valueOf(item) === null),
    },
  ];
}

function groupByState(items: Item[], states: State[] | undefined): ViewGroup[] {
  if (states && states.length > 0) {
    return [...states]
      .sort((a, b) => a.position - b.position)
      .map((state) => ({
        key: state.id,
        label: state.name,
        dotClassName: CATEGORY_META[state.category].dotClassName,
        items: items.filter((item) => item.state.id === state.id),
      }));
  }
  // All-projects: same-named states across projects share a bucket.
  const seen = new Map<string, ViewGroup>();
  for (const item of items) {
    const bucket = seen.get(item.state.name);
    if (bucket) {
      bucket.items.push(item);
    } else {
      seen.set(item.state.name, {
        key: item.state.name,
        label: item.state.name,
        dotClassName: CATEGORY_META[item.state.category].dotClassName,
        items: [item],
      });
    }
  }
  return [...seen.values()].sort(
    (a, b) =>
      CATEGORY_META[a.items[0].state.category].order -
        CATEGORY_META[b.items[0].state.category].order || a.label.localeCompare(b.label),
  );
}

function groupByAssignee(items: Item[]): ViewGroup[] {
  const buckets = new Map<string, ViewGroup>();
  for (const item of items) {
    const key = item.assignee?.id ?? UNASSIGNED_KEY;
    const bucket = buckets.get(key);
    if (bucket) {
      bucket.items.push(item);
    } else {
      buckets.set(key, {
        key,
        label: item.assignee?.name ?? UNASSIGNED_LABEL,
        items: [item],
      });
    }
  }
  return withUnsetLast(buckets, UNASSIGNED_KEY, UNASSIGNED_LABEL);
}

function groupByTeam(items: Item[]): ViewGroup[] {
  const buckets = new Map<string, ViewGroup>();
  for (const item of items) {
    const key = item.team?.id ?? NO_TEAM_KEY;
    const bucket = buckets.get(key);
    if (bucket) {
      bucket.items.push(item);
    } else {
      buckets.set(key, { key, label: item.team?.name ?? NO_TEAM_LABEL, items: [item] });
    }
  }
  return withUnsetLast(buckets, NO_TEAM_KEY, NO_TEAM_LABEL);
}

/** Named buckets alphabetical, then the always-present unset bucket last. */
function withUnsetLast(
  buckets: Map<string, ViewGroup>,
  unsetKey: string,
  unsetLabel: string,
): ViewGroup[] {
  const unset = buckets.get(unsetKey) ?? { key: unsetKey, label: unsetLabel, items: [] };
  const named = [...buckets.values()].filter((bucket) => bucket.key !== unsetKey);
  named.sort((a, b) => a.label.localeCompare(b.label));
  return [...named, unset];
}
