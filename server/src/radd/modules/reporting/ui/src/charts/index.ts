/** The chart kit the reports draw with (spec 19) — the host's report cards import it here; a
 * plugin's report reaches the same components through the slots in `report-contract` (RADD-1386). */
export { BarChart } from "./BarChart";
export { ChartHeightContext } from "./ChartHeightContext";
export { ChartLegend } from "./ChartLegend";
export { LineChart, type LineSeries } from "./LineChart";
export { ReportCard } from "./ReportCard";
export { StackedBarChart } from "./StackedBarChart";
export { CardBody, ScopeNote, scopeNote } from "./report-state";
export type { BarDatum, LegendEntry, StackSegment, StackedBar } from "../report-contract";
