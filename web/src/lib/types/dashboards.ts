/** Composable dashboards (spec 75). */
import type { ItemKindValue } from "./items";
import type { ReportIntervalValue, ReportMeasureValue } from "./reporting";
import type { ShareLevelValue, ShareSubjectRef, ViewShare } from "./views";
// ---------------------------------------------------------------------------
// Composable dashboards (spec 75 — /dashboards). Ownership + sharing mirror
// views (spec 57): same ShareLevel vocabulary, same wire shapes.
// ---------------------------------------------------------------------------

/** Mirror of the backend WidgetType enum — what a dashboard widget renders. */
export const WidgetType = {
  reportThroughput: "report_throughput",
  reportCfd: "report_cfd",
  reportTimeInState: "report_time_in_state",
  reportVelocity: "report_velocity",
  reportBurnup: "report_burnup",
  reportSla: "report_sla",
  slqCount: "slq_count",
  slqList: "slq_list",
  viewCount: "view_count",
} as const;
export type WidgetTypeValue = (typeof WidgetType)[keyof typeof WidgetType];

/**
 * Per-type widget config. The server validates the exact shape per type
 * (discriminated union) — client-side one bag of optionals keeps the forms
 * and renderers simple; each widget type reads only its own fields.
 */
export interface WidgetConfig {
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
  widget_type: WidgetTypeValue;
  /** Optional card-label override. */
  title: string | null;
  /** Grid thirds spanned (1..3). */
  width: number;
  position: number;
  config: WidgetConfig;
}

export interface Dashboard {
  id: string;
  name: string;
  description: string;
  owner_id: string | null;
  owner: ShareSubjectRef | null;
  /** Wire name for "everyone on this server" (spec 86). */
  global_access: ShareLevelValue | null;
  /** Same wire shape as view shares (the spec-57 idiom). */
  shares: ViewShare[];
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

export interface DashboardCreate {
  name: string;
  description?: string;
  /** Wire name for "everyone on this server" (spec 86). */
  global_access?: ShareLevelValue | null;
  shares?: { user_id?: string; team_id?: string; level: ShareLevelValue }[];
}

export interface DashboardUpdate {
  name?: string;
  description?: string;
  position?: number;
}

/** POST /dashboards/{id}/widgets — the server discriminates on widget_type. */
export interface DashboardWidgetCreate {
  widget_type: WidgetTypeValue;
  title?: string | null;
  width?: number;
  position?: number;
  config: WidgetConfig;
}

/** PATCH a widget — config (when sent) revalidates against the stored type. */
export interface DashboardWidgetUpdate {
  title?: string | null;
  width?: number;
  position?: number;
  config?: WidgetConfig;
}
