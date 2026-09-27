import { useEffect } from "react";
import { Button, SelectField, Slot, type DashboardWidgetConfigProps } from "@radd/plugin-sdk";
import { PROJECT_SELECT_SLOT, type ProjectSelectProps } from "@radd-plugin-ui/projects/picker-contract";
import { SLA_REPORT_DEFAULT_WEEKS, SLA_REPORT_WEEKS_OPTIONS, type SlaWidgetConfig } from "./report";

/** The Projects plugin's select — it owns the rendering and the queries; the host's own dashboards
 *  form reaches it the same way. */
function ProjectSelect(props: ProjectSelectProps) {
  const fallback = <Button disabled variant="secondary" aria-label={props.label}>Selection unavailable</Button>;
  return <Slot id={PROJECT_SELECT_SLOT} {...props} fallback={fallback} errorFallback={fallback} />;
}

/** The widget's stored config, with the report's defaults where the bag says nothing. */
function settingsOf(config: Record<string, unknown>): Required<SlaWidgetConfig> {
  const project = config.project_id;
  const weeks = config.weeks;
  return {
    project_id: typeof project === "string" && project ? project : null,
    weeks: typeof weeks === "number" && SLA_REPORT_WEEKS_OPTIONS.includes(weeks) ? weeks : SLA_REPORT_DEFAULT_WEEKS,
  };
}

/**
 * The "Service desk SLA" widget's settings (RADD-1462), drawn inside the dashboards Add/Edit widget
 * dialog through `dashboard.widget.config`: the report's scope (one project, or every project the
 * viewer can read) and its window. The server checks the shape on save (`SlaWidgetConfig`).
 */
export function SlaWidgetConfigFields({ config, onChange }: DashboardWidgetConfigProps) {
  const settings = settingsOf(config);
  // A fresh widget's bag is empty: write the defaults in, so what is saved is what the form shows.
  useEffect(() => {
    if (config.weeks !== settings.weeks || (config.project_id ?? null) !== settings.project_id) onChange({ ...settings });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <>
      <ProjectSelect label="Project (optional)" value={settings.project_id ?? ""} emptyLabel="All projects" emptyValue=""
        onChange={(id) => onChange({ ...settings, project_id: id || null })} />
      <SelectField label="Window" value={String(settings.weeks)} onChange={(event) => onChange({ ...settings, weeks: Number(event.target.value) })}>
        {SLA_REPORT_WEEKS_OPTIONS.map((n) => <option key={n} value={String(n)}>Last {n} weeks</option>)}
      </SelectField>
    </>
  );
}
