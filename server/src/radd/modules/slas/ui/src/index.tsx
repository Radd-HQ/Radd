import {
  definePlugin, itemAttribute, SlotId, type DashboardWidgetConfigProps, type Item, type ProjectSettingsPageProps,
} from "@radd/plugin-sdk";
import { REPORT_SECTION_SLOT, type ReportSectionProps } from "@radd-plugin-ui/reporting/report-contract";
import { SLA_WIDGET_TYPE, type SlaWidgetConfig } from "./report";
import { SlaReportCard } from "./SlaReportCard";
import { SlaWidgetConfigFields } from "./SlaWidgetConfigFields";
import { SlaPanel } from "./SlaPanel";
import { SlaRowChip } from "./SlaChips";
import { SlaKind, timersSource, type SlaBatchTimer } from "./timers";
import { SlaSettingsPage } from "./settings/SlaSettingsPage";

/** The project-settings segment this plugin's page answers (`/p/<KEY>/settings/sla`); the manifest's
 *  `NavItemSpec(section="project_settings", path="sla")` lists it (`types.SETTINGS_PAGE_SEGMENT`). */
const SETTINGS_SEGMENT = "sla";

/** The card designer's stand-in: one healthy response timer, so a placed cell shows a real chip. */
const SAMPLE_TIMERS: SlaBatchTimer[] = [
  { policy_name: "Standard support", kind: SlaKind.response, due_at: null, met_at: null,
    breached: false, paused: false, remaining_seconds: 4 * 3600 },
];

/** slas: the SLA report + dashboard widget, the rail timers, the SLA column/card cell (the `slas.timers` batch),
 *  and the project SLA settings page. The queue view type needs no UI — the host draws it. */
export default definePlugin({
  querySources: [timersSource],
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
    {
      // RADD-1462: the widget's settings form, drawn inside dashboards' Add/Edit widget dialog.
      id: "widget-config",
      slot: SlotId.dashboardWidgetConfig,
      match: SLA_WIDGET_TYPE,
      toggleable: false,
      label: "Service desk SLA widget settings",
      render: (props) => <SlaWidgetConfigFields {...(props as unknown as DashboardWidgetConfigProps)} />,
    },
    {
      id: "rail",
      slot: SlotId.issuePanelSection,
      order: 40,
      label: "SLA timers on the issue",
      render: (props) => <SlaPanel itemId={(props as { item: Item }).item.id} />,
    },
    {
      id: "settings",
      slot: SlotId.projectSettingsPage,
      match: SETTINGS_SEGMENT,
      label: "Project SLA settings page",
      render: (props) => <SlaSettingsPage project={(props as unknown as ProjectSettingsPageProps).project} />,
    },
    itemAttribute<SlaBatchTimer[]>({
      id: "slas.timer",
      label: "SLA",
      width: 96,
      minWidth: 56,
      source: timersSource.key,
      sample: SAMPLE_TIMERS,
      render: ({ value }) => <SlaRowChip timers={value} />,
    }),
  ],
});
