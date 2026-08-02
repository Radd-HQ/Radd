import { ReportMeasure, type ReportMeasureValue } from "../../lib/types";

/** The velocity/burnup Count ↔ Points toggle options (spec 70). */
export const MEASURE_OPTIONS: readonly { value: ReportMeasureValue; label: string }[] = [
  { value: ReportMeasure.count, label: "Count" },
  { value: ReportMeasure.points, label: "Points" },
];
