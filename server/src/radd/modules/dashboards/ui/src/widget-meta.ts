/** Widget vocabulary: names, the add-widget picker's options, and which config each type takes. */
import { ItemKind, PersonalWidgetType, ReportInterval, ReportMeasure, WidgetType, type ItemKindValue } from "./types";

/** A card's heading when it carries no title override (a contributed type uses its label). */
export const CARD_LABELS: Record<string, string> = {
  [PersonalWidgetType.assigned]: "Assigned to me",
  [PersonalWidgetType.due]: "Due soon",
  [PersonalWidgetType.activity]: "My activity",
  [PersonalWidgetType.inbox]: "Inbox",
  [PersonalWidgetType.starred]: "Starred",
  [PersonalWidgetType.requests]: "My requests",
  [PersonalWidgetType.forms]: "Request forms",
  [PersonalWidgetType.recent]: "Recently viewed",
  [WidgetType.slqCount]: "Issue count",
  [WidgetType.slqList]: "Issue list",
  [WidgetType.viewCount]: "Saved-view count",
  [WidgetType.reportThroughput]: "Throughput",
  [WidgetType.reportCfd]: "Cumulative flow",
  [WidgetType.reportTimeInState]: "Time in state",
  [WidgetType.reportVelocity]: "Velocity",
  [WidgetType.reportBurnup]: "Burnup",
  [WidgetType.reportSla]: "Service desk SLA",
};

/** My Work's own kinds, offered only on My Work. */
export const PERSONAL_OPTIONS: readonly { value: string; label: string }[] =
  Object.values(PersonalWidgetType).map((value) => ({ value, label: CARD_LABELS[value] }));

/** The builtin types a shared dashboard (and My Work) offers — "cycles", never "sprint". */
export const WIDGET_TYPE_OPTIONS: readonly { value: string; label: string }[] = [
  { value: WidgetType.slqCount, label: "Issue count (SLQ)" },
  { value: WidgetType.slqList, label: "Issue list (SLQ)" },
  { value: WidgetType.viewCount, label: "Saved-view count" },
  { value: WidgetType.reportThroughput, label: "Throughput chart" },
  { value: WidgetType.reportCfd, label: "Cumulative flow chart" },
  { value: WidgetType.reportTimeInState, label: "Time in state" },
  { value: WidgetType.reportVelocity, label: "Velocity across cycles" },
  { value: WidgetType.reportBurnup, label: "Cycle burnup" },
  { value: WidgetType.reportSla, label: "Service desk SLA" },
];

/** The host's report cards draw these (the SDK's ReportWidget bridge). */
export const REPORT_TYPES: readonly string[] = [
  WidgetType.reportThroughput, WidgetType.reportCfd, WidgetType.reportTimeInState,
  WidgetType.reportVelocity, WidgetType.reportBurnup,
];
export const PROJECT_TYPES: readonly string[] = [WidgetType.reportThroughput, WidgetType.reportCfd, WidgetType.reportTimeInState];
export const OPTIONAL_PROJECT_TYPES: readonly string[] = [
  WidgetType.reportSla, PersonalWidgetType.activity, WidgetType.slqCount, WidgetType.slqList,
];
export const SLQ_TYPES: readonly string[] = [WidgetType.slqCount, WidgetType.slqList];
export const MEASURE_TYPES: readonly string[] = [WidgetType.reportVelocity, WidgetType.reportBurnup];

export const WIDTH_OPTIONS = Array.from({ length: 11 }, (_, i) => ({ value: String(i + 2), label: `${i + 2} / 12` }));
export const INTERVAL_OPTIONS = [
  { value: ReportInterval.day, label: "Day" },
  { value: ReportInterval.week, label: "Week" },
];
/** The velocity/burnup Count ↔ Points toggle (spec 70). */
export const MEASURE_OPTIONS = [
  { value: ReportMeasure.count, label: "Count" },
  { value: ReportMeasure.points, label: "Points" },
];
export const KIND_OPTIONS: readonly { value: ItemKindValue; label: string }[] = [
  { value: ItemKind.epic, label: "Epics" },
  { value: ItemKind.issue, label: "Issues" },
  { value: ItemKind.subtask, label: "Subtasks" },
];
export const VELOCITY_LAST_OPTIONS: readonly number[] = [3, 5, 8, 12];
/** GET /sla-report caps the window at 26 weeks. */
export const SLA_WEEKS_OPTIONS: readonly number[] = [4, 8, 12, 26];
export const SLQ_LIST_ROWS: readonly number[] = [5, 10, 15, 20];

/** A widget's effective query: its own `q` AND the page-wide filter, keeping its ORDER BY last. */
export function andFilter(base: string, filter?: string): string {
  if (!filter) return base;
  const order = /\border\s+by\b/i.exec(base);
  const where = (order ? base.slice(0, order.index) : base).trim();
  const parts = [...(where ? [where] : []), filter].map((part) => `(${part})`);
  return parts.join(" AND ") + (order ? ` ${base.slice(order.index).trim()}` : "");
}
