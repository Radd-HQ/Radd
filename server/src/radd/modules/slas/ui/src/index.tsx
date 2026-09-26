import { definePlugin, itemAttribute, SlotId, type Item, type ProjectSettingsPageProps } from "@radd/plugin-sdk";
import { REPORT_SECTION_SLOT, type ReportSectionProps } from "@radd-plugin-ui/reporting/report-contract";
import { SLA_WIDGET_TYPE, type SlaWidgetConfig } from "./report";
import { SlaReportCard } from "./SlaReportCard";
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

/** The slas plugin's UI remote: the SLA report (RADD-1386) on the reports pages and as the
 * "Service desk SLA" dashboard widget, the timers (RADD-1394) — the issue rail's SLA section
 * and the SLA list column / board-card cell, fed by its `slas.timers` batch — and the project's
 * SLA settings page (RADD-1396). Disabling the plugin withdraws all of them; a saved view that
 * names the column keeps the id and skips it. The queue view type needs no UI here: the manifest
 * declares it a list surface over this plugin's urgency-ordered rows, which the host draws. */
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
