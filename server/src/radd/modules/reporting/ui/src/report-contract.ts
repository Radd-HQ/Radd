/**
 * The reporting module's public UI contract (RADD-1386) — slot ids and their props, nothing else.
 *
 * A plugin's report joins the reports pages through REPORT_SECTION_SLOT, and draws with the same
 * chart kit the host's own report cards use by rendering the slots below. The implementations are
 * this package's contributions, registered at boot, so a plugin's charts share the theme and the
 * dashboard widget's plot height instead of shipping a second copy of the kit.
 */
import type { ReactNode } from "react";

/** A section on the reports pages. The project page passes `projectId`; the global page omits it
 * (every project the reader can see). `q` is the page's SLQ filter, ANDed server-side. */
export const REPORT_SECTION_SLOT = "reporting.section";
export interface ReportSectionProps {
  projectId?: string;
  q?: string;
}

/** Which projects a cross-project figure was computed over (RADD-789). */
export interface ReportScope {
  covered: string[];
  total: number;
}

/** A titled report card that states its scope and gates its body on loading, error and empty. */
export const REPORT_CARD_SLOT = "reporting.card";
export interface ReportCardProps {
  title: string;
  description?: string;
  /** Rendered at the top right: the report's own window or measure pickers. */
  controls?: ReactNode;
  scope?: ReportScope;
  /** Not `pending`: <Slot> reserves that name for its own not-yet-registered state. */
  loading: boolean;
  error: string | null;
  empty: boolean;
  emptyMessage: string;
  children: ReactNode;
}

/** Stacked vertical bars, one stack per bucket. */
export const STACKED_BAR_CHART_SLOT = "reporting.chart.stacked-bar";
export interface StackSegment {
  key: string;
  label: string;
  value: number;
  color: string;
}
export interface StackedBar {
  label: string;
  segments: StackSegment[];
}
export interface StackedBarChartProps {
  bars: StackedBar[];
  height?: number;
  ariaLabel: string;
}

/** Vertical bars, one per bucket. */
export const BAR_CHART_SLOT = "reporting.chart.bar";
export interface BarDatum {
  label: string;
  value: number;
  /** Hover title (defaults to `label: value`). */
  title?: string;
}
export interface BarChartProps {
  data: BarDatum[];
  color: string;
  height?: number;
  ariaLabel: string;
}

/** Swatch + label legend under a chart. */
export const CHART_LEGEND_SLOT = "reporting.chart.legend";
export interface LegendEntry {
  label: string;
  color: string;
}
export interface ChartLegendProps {
  entries: LegendEntry[];
}
