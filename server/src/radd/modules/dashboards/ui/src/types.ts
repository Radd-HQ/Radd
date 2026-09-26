/** Composable dashboards (spec 75) and My Work's layout — the `/dashboards` wire shapes. */

/** The builtin widget types a shared dashboard carries — mirror of the backend `WidgetType`. */
export const WidgetType = {
  reportThroughput: "report_throughput",
  reportCfd: "report_cfd",
  reportTimeInState: "report_time_in_state",
  reportVelocity: "report_velocity",
  reportBurnup: "report_burnup",
  /** Builtin, but the slas plugin draws it through `dashboard.widget`. */
  reportSla: "report_sla",
  slqCount: "slq_count",
  slqList: "slq_list",
  viewCount: "view_count",
} as const;
export type WidgetTypeValue = (typeof WidgetType)[keyof typeof WidgetType];

/** My Work's OWN widget kinds — the shell's basics and forms' request widgets (a core module).
 * A plugin's personal widget is a contributed type instead (`widget_types`, `personal: true`). */
export const PersonalWidgetType = {
  assigned: "assigned",
  due: "due",
  activity: "activity",
  inbox: "inbox",
  starred: "starred",
  requests: "requests",
  forms: "forms",
  recent: "recent",
} as const;

export const ReportInterval = { day: "day", week: "week" } as const;
export type ReportIntervalValue = (typeof ReportInterval)[keyof typeof ReportInterval];
export const ReportMeasure = { count: "count", points: "points" } as const;
export type ReportMeasureValue = (typeof ReportMeasure)[keyof typeof ReportMeasure];
export const ItemKind = { epic: "epic", issue: "issue", subtask: "subtask" } as const;
export type ItemKindValue = (typeof ItemKind)[keyof typeof ItemKind];

/**
 * Per-type widget config. The server validates the exact shape per type (a discriminated union);
 * client-side one bag of optionals keeps the forms and renderers simple — each type reads only its
 * own fields. A plugin's widget type owns its config entirely.
 */
export interface WidgetConfig {
  start?: string;
  end?: string;
  project_id?: string | null;
  cycle_id?: string;
  view_id?: string;
  interval?: ReportIntervalValue;
  kind?: ItemKindValue | null;
  last?: number;
  measure?: ReportMeasureValue;
  weeks?: number;
  q?: string;
  label?: string | null;
  limit?: number;
}

export interface DashboardWidget {
  id: string;
  /** A builtin type, one of My Work's kinds, or a plugin-contributed key. */
  widget_type: string;
  /** Optional card-label override. */
  title: string | null;
  /** Grid columns spanned (2..12). */
  width: number;
  height: number;
  collapsed: boolean;
  position: number;
  config: WidgetConfig;
}

export interface Dashboard {
  id: string;
  name: string;
  description: string;
  owner_id: string | null;
  owner: { id: string; name: string } | null;
  /** "Everyone on this server" (spec 86): viewer | editor | null. */
  global_access: string | null;
  /** Visible beyond the owner (server-wide or any grant). */
  shared: boolean;
  /** Per-actor capabilities, computed server-side. */
  can_edit: boolean;
  can_manage: boolean;
  position: number;
  widgets: DashboardWidget[];
  created_at: string;
  updated_at: string;
}

/** POST /dashboards — a name; sharing comes later through the Share dialog. */
export interface DashboardCreate {
  name: string;
}

export interface DashboardUpdate {
  name?: string;
  description?: string;
}

/** POST /dashboards/{id}/widgets — the server discriminates on widget_type. */
export interface DashboardWidgetCreate {
  widget_type: string;
  title?: string | null;
  width?: number;
  position?: number;
  config: WidgetConfig;
}

/** PATCH a widget — config (when sent) revalidates against the stored type. */
export interface DashboardWidgetUpdate {
  title?: string | null;
  width?: number;
  config?: WidgetConfig;
}

/** One entry of GET /dashboards/my-work/activity. */
export interface ActivityPage {
  entries: { id: number; at: string; action: string; item_key: string; comment_id: string | null }[];
  next: number | null;
}
