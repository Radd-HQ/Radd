import { definePlugin } from "@radd/plugin-sdk";
import { BarChart } from "./charts/BarChart";
import { ChartLegend } from "./charts/ChartLegend";
import { ReportFrame } from "./charts/ReportFrame";
import { StackedBarChart } from "./charts/StackedBarChart";
import {
  BAR_CHART_SLOT,
  CHART_LEGEND_SLOT,
  REPORT_CARD_SLOT,
  STACKED_BAR_CHART_SLOT,
  type BarChartProps,
  type ChartLegendProps,
  type ReportCardProps,
  type StackedBarChartProps,
} from "./report-contract";

/** The chart kit, contributed to the contract's slots so a plugin's report (slas) draws with the host's charts. */
export default definePlugin({
  contributions: [
    { id: "card", slot: REPORT_CARD_SLOT, toggleable: false, render: (props) => <ReportFrame {...(props as unknown as ReportCardProps)} /> },
    { id: "stacked-bar", slot: STACKED_BAR_CHART_SLOT, toggleable: false, render: (props) => <StackedBarChart {...(props as unknown as StackedBarChartProps)} /> },
    { id: "bar", slot: BAR_CHART_SLOT, toggleable: false, render: (props) => <BarChart {...(props as unknown as BarChartProps)} /> },
    { id: "legend", slot: CHART_LEGEND_SLOT, toggleable: false, render: (props) => <ChartLegend {...(props as unknown as ChartLegendProps)} /> },
  ],
});
