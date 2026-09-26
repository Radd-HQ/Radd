import { isoDaysAgo, type ReportWidgetProps } from "@radd/plugin-sdk";
import { REPORT_DEFAULT_RANGE_DAYS } from "../../lib/constants";
import { usePointsEnabled } from "../../lib/hooks";
import {
  ReportInterval,
  ReportMeasure,
  type ItemKindValue,
  type ReportIntervalValue,
  type ReportMeasureValue,
} from "../../lib/types";
import { WidgetType } from "@radd-plugin-ui/dashboards/types";
import { BurnupCard } from "./BurnupCard";
import { CumulativeFlowCard } from "./CumulativeFlowCard";
import { ThroughputCard } from "./ThroughputCard";
import { TimeInStateCard } from "./TimeInStateCard";
import { VelocityCard } from "./VelocityCard";

/** The widget config the report types store (the dashboards plugin validates it server-side). */
interface ReportConfig {
  project_id?: string | null;
  interval?: ReportIntervalValue;
  kind?: ItemKindValue | null;
  last?: number;
  measure?: ReportMeasureValue;
  cycle_id?: string;
}

/**
 * The shell's report cards as dashboard widgets (RADD-1393) — what the SDK's ReportWidget bridge
 * draws for the dashboards package, which cannot reach these host components itself. Each card
 * contains its own loading and error states; a widget missing its scope reads as Unavailable.
 */
export function ReportWidget({ widgetType, config: raw, title, filterQuery }: ReportWidgetProps) {
  const config = raw as ReportConfig;
  const pointsEnabled = usePointsEnabled();
  const showPoints = pointsEnabled || config.measure === ReportMeasure.points;
  switch (widgetType) {
    case WidgetType.reportThroughput:
    case WidgetType.reportCfd: {
      if (!config.project_id) return <Unavailable title={title} />;
      const range = { projectId: config.project_id, start: isoDaysAgo(REPORT_DEFAULT_RANGE_DAYS), end: isoDaysAgo(0),
        interval: config.interval ?? ReportInterval.week, q: filterQuery };
      return widgetType === WidgetType.reportThroughput ? <ThroughputCard {...range} /> : <CumulativeFlowCard {...range} />;
    }
    case WidgetType.reportTimeInState:
      return config.project_id
        ? <TimeInStateCard projectId={config.project_id} initialKind={config.kind ?? undefined} q={filterQuery} />
        : <Unavailable title={title} />;
    case WidgetType.reportVelocity:
      return <VelocityCard showPoints={showPoints} initialLast={config.last} initialMeasure={config.measure} q={filterQuery} />;
    case WidgetType.reportBurnup:
      return config.cycle_id
        ? <BurnupCard showPoints={showPoints} fixedCycleId={config.cycle_id} initialMeasure={config.measure} q={filterQuery} />
        : <Unavailable title={title} />;
    default:
      return <Unavailable title={title} />;
  }
}

function Unavailable({ title }: { title?: string | null }) {
  return (
    <div className="rounded-xl border border-dashed border-subtle px-4 py-6 text-center text-xs text-fg-faint">
      {title ? `${title} — unavailable` : "Unavailable"}
      <span className="mt-0.5 block text-[11px] text-fg-faint">You may not have access to this widget’s data.</span>
    </div>
  );
}
