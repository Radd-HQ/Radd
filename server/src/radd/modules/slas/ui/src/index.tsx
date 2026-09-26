import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { REPORT_SECTION_SLOT, type ReportSectionProps } from "@radd-plugin-ui/reporting/report-contract";
import { SLA_WIDGET_TYPE, type SlaWidgetConfig } from "./report";
import { SlaReportCard } from "./SlaReportCard";

/** The slas plugin's UI remote (RADD-1386): the SLA report, on the reports pages (one project, or
 * every readable project on the global page) and as the "Service desk SLA" dashboard widget.
 * Disabling the plugin withdraws both — its endpoint is gone with it. */
export default definePlugin({
  contributions: [
    {
      id: "report",
      slot: REPORT_SECTION_SLOT,
      label: "Service desk SLA report",
      render: (props) => {
        const { projectId, q } = props as ReportSectionProps;
        return <SlaReportCard projectId={projectId} q={q} />;
      },
    },
    {
      id: "widget",
      slot: SlotId.dashboardWidget,
      match: SLA_WIDGET_TYPE,
      label: "Service desk SLA widget",
      render: (props) => {
        const { config, filterQuery } = props as { config: SlaWidgetConfig; filterQuery?: string };
        return (
          <SlaReportCard projectId={config.project_id ?? undefined} initialWeeks={config.weeks} q={filterQuery} />
        );
      },
    },
  ],
});
