import { ProjectSelect } from "../projects/ProjectSelect";
import { ViewSelect } from "../views/ViewSelect";
import { CycleSelect } from "../cycles/CycleSelect";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SlotId, useDisabledMatches } from "@radd/plugin-sdk";
import { api } from "../../lib/api";
import {
  apiDashboardWidgetPath,
  apiDashboardWidgetsPath,
  SLA_REPORT_WEEKS_OPTIONS,
  VELOCITY_LAST_OPTIONS,
} from "../../lib/constants";
import { Entity, invalidateEntities } from "../../lib/cache";
import { SlqProbeStatus, useSlqValidation } from "../../lib/hooks";
import { KIND_META, KIND_ORDER, REPORT_INTERVAL_LABELS, REPORT_INTERVAL_ORDER } from "../../lib/meta";
import { capabilitiesQuery } from "../../lib/queries";
import { slqErrorOf } from "../../lib/slq";
import {
  ReportInterval,
  ReportMeasure,
  WidgetType,
  type Dashboard,
  type DashboardWidget,
  type DashboardWidgetCreate,
  type DashboardWidgetUpdate,
  type ItemKindValue,
  type ReportIntervalValue,
  type ReportMeasureValue,
  type WidgetConfig,
  type WidgetTypeValue,
} from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import { Segmented } from "../reports/report-state";
import { MEASURE_OPTIONS } from "../reports/measure";
import { SlqEditor } from "../views/SlqEditor";
import { ErrorText } from "../ErrorText";

/** Widget-type picker entries (spec 75) — labels use "cycles", never "sprint". */
const WIDGET_TYPE_OPTIONS: readonly { value: WidgetTypeValue; label: string }[] = [
  { value: WidgetType.slqCount, label: "Issue count (SLQ)" },
  { value: WidgetType.slqList, label: "Issue list (SLQ)" },
  { value: WidgetType.viewCount, label: "Saved-view count" },
  { value: WidgetType.reportThroughput, label: "Throughput chart" },
  { value: WidgetType.reportCfd, label: "Cumulative flow chart" },
  { value: WidgetType.reportTimeInState, label: "Time in state" },
  { value: WidgetType.reportVelocity, label: "Velocity across cycles" },
  { value: WidgetType.reportBurnup, label: "Cycle burnup" },
  { value: WidgetType.reportSla, label: "Service desk SLA" },
];

const WIDTH_OPTIONS: readonly { value: string; label: string }[] = [
  { value: "1", label: "⅓" },
  { value: "2", label: "⅔" },
  { value: "3", label: "Full" },
];

const INTERVAL_OPTIONS = REPORT_INTERVAL_ORDER.map((interval) => ({
  value: interval,
  label: REPORT_INTERVAL_LABELS[interval],
}));

/** Sentinel option values (never real ids/kinds). */
const NONE = "";

const PROJECT_TYPES: readonly WidgetTypeValue[] = [
  WidgetType.reportThroughput,
  WidgetType.reportCfd,
  WidgetType.reportTimeInState,
];
const OPTIONAL_PROJECT_TYPES: readonly WidgetTypeValue[] = [
  WidgetType.reportSla,
  WidgetType.slqCount,
  WidgetType.slqList,
];
const SLQ_TYPES: readonly WidgetTypeValue[] = [WidgetType.slqCount, WidgetType.slqList];
const MEASURE_TYPES: readonly WidgetTypeValue[] = [
  WidgetType.reportVelocity,
  WidgetType.reportBurnup,
];

/**
 * Add/Edit widget dialog (spec 75): type picker + a per-type config form —
 * project/cycle/view selects from the existing queries, an SLQ input with the
 * ordinary live validation, measure/interval toggles where relevant. The
 * server re-validates shape + references on save (422/409).
 */
export function WidgetModal({
  dashboard,
  widget,
  onClose,
}: {
  dashboard: Dashboard;
  /** When set, edit this widget's config in place (type is immutable). */
  widget?: DashboardWidget;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<string>(widget?.widget_type ?? WidgetType.slqCount);
  const [title, setTitle] = useState(widget?.title ?? "");
  const [width, setWidth] = useState(String(widget?.width ?? 1));
  const [projectId, setProjectId] = useState(widget?.config.project_id ?? NONE);
  const [interval, setInterval] = useState<ReportIntervalValue>(
    widget?.config.interval ?? ReportInterval.week,
  );
  const [kind, setKind] = useState<ItemKindValue | typeof NONE>(widget?.config.kind ?? NONE);
  const [last, setLast] = useState(String(widget?.config.last ?? 5));
  const [measure, setMeasure] = useState<ReportMeasureValue>(
    widget?.config.measure ?? ReportMeasure.count,
  );
  const [cycleId, setCycleId] = useState(widget?.config.cycle_id ?? NONE);
  const [weeks, setWeeks] = useState(String(widget?.config.weeks ?? 12));
  const [q, setQ] = useState(widget?.config.q ?? "");
  const [label, setLabel] = useState(widget?.config.label ?? "");
  const [limit, setLimit] = useState(String(widget?.config.limit ?? 10));
  const [viewId, setViewId] = useState(widget?.config.view_id ?? NONE);

  // Plugin-contributed widget types (spec 94) join the Type dropdown; the plugin renders them and
  // needs no builtin config (buildConfig defaults to {}).
  const { data: capsManifest } = useQuery(capabilitiesQuery);
  // A turned-off dashboard.widget contribution (spec 94) drops out of the type dropdown too.
  const disabledWidgetTypes = useDisabledMatches(SlotId.dashboardWidget);
  const pluginWidgetTypes = (capsManifest?.widget_types ?? []).filter(
    (t) => !disabledWidgetTypes.has(t.key),
  );

  // Plugin widget types match none of these builtin sets (they need no config) — cast is safe.
  const needsProject = PROJECT_TYPES.includes(type as WidgetTypeValue);
  const optionalProject = OPTIONAL_PROJECT_TYPES.includes(type as WidgetTypeValue);
  const isSlq = SLQ_TYPES.includes(type as WidgetTypeValue);
  // Live SLQ validation (spec 55 idiom) — scoped to the picked project.
  const probe = useSlqValidation(isSlq && projectId ? projectId : null, isSlq ? q : "");

  const buildConfig = (): WidgetConfig => {
    switch (type) {
      case WidgetType.reportThroughput:
      case WidgetType.reportCfd:
        return { project_id: projectId, interval };
      case WidgetType.reportTimeInState:
        return { project_id: projectId, kind: kind === NONE ? null : kind };
      case WidgetType.reportVelocity:
        return { last: Number(last), measure };
      case WidgetType.reportBurnup:
        return { cycle_id: cycleId, measure };
      case WidgetType.reportSla:
        return { project_id: projectId || null, weeks: Number(weeks) };
      case WidgetType.slqCount:
        return { project_id: projectId || null, q, label: label.trim() || null };
      case WidgetType.slqList:
        return { project_id: projectId || null, q, limit: Number(limit) };
      case WidgetType.viewCount:
        return { view_id: viewId };
      default:
        return {};
    }
  };

  const ready =
    (!needsProject || projectId !== NONE) &&
    (type !== WidgetType.reportBurnup || cycleId !== NONE) &&
    (type !== WidgetType.viewCount || viewId !== NONE) &&
    (!isSlq || probe.status !== SlqProbeStatus.invalid);

  const save = useMutation({
    mutationFn: async () => {
      const common = { title: title.trim() || null, width: Number(width), config: buildConfig() };
      if (widget) {
        return api.patch<Dashboard>(
          apiDashboardWidgetPath(dashboard.id, widget.id),
          common satisfies DashboardWidgetUpdate,
        );
      }
      return api.post<Dashboard>(apiDashboardWidgetsPath(dashboard.id), {
        widget_type: type as WidgetTypeValue,
        position: dashboard.widgets.length,
        ...common,
      } satisfies DashboardWidgetCreate);
    },
    onSuccess: async () => {
      await invalidateEntities(queryClient, Entity.dashboard);
      onClose();
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (ready) save.mutate();
  };

  // The server re-parses SLQ on save — a 422 here means the draft outran the probe.
  const saveSlqError = save.isError ? slqErrorOf(save.error) : null;

  return (
    <Modal title={widget ? "Edit widget" : "Add widget"} onClose={onClose} wide>
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <SelectField
            label="Type"
            value={type}
            onChange={(event) => setType(event.target.value as WidgetTypeValue)}
            disabled={Boolean(widget)}
            hint={widget ? "Fixed — remove and re-add to change the type" : undefined}
          >
            {WIDGET_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
            {pluginWidgetTypes.map((t) => (
              <option key={t.key} value={t.key}>
                {t.label}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Title (optional)"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Card label override"
            maxLength={200}
          />
        </div>

        {(needsProject || optionalProject) && (
          <ProjectSelect label={needsProject ? "Project" : "Project (optional)"}
            value={projectId ?? NONE} onChange={setProjectId}
            emptyLabel={needsProject ? null : "All projects"} emptyValue={NONE} />
        )}

        {(type === WidgetType.reportThroughput || type === WidgetType.reportCfd) && (
          <LabeledControl label="Bucket interval">
            <Segmented
              ariaLabel="Bucket interval"
              value={interval}
              options={INTERVAL_OPTIONS}
              onChange={setInterval}
            />
          </LabeledControl>
        )}

        {type === WidgetType.reportTimeInState && (
          <SelectField
            label="Kind"
            value={kind}
            onChange={(event) => setKind(event.target.value as ItemKindValue | typeof NONE)}
          >
            <option value={NONE}>All kinds</option>
            {KIND_ORDER.map((entry) => (
              <option key={entry} value={entry}>
                {KIND_META[entry].label}s
              </option>
            ))}
          </SelectField>
        )}

        {type === WidgetType.reportVelocity && (
          <SelectField
            label="Cycles shown"
            value={last}
            onChange={(event) => setLast(event.target.value)}
          >
            {VELOCITY_LAST_OPTIONS.map((option) => (
              <option key={option} value={String(option)}>
                Last {option}
              </option>
            ))}
          </SelectField>
        )}

        {type === WidgetType.reportBurnup && (
          <CycleSelect label="Cycle" value={cycleId} onChange={setCycleId} emptyValue={NONE}
            emptyLabel={null} datedOnly hint="Dated cycles only — a draft cycle has no window to chart" />
        )}

        {MEASURE_TYPES.includes(type as WidgetTypeValue) && (
          <LabeledControl label="Measure">
            <Segmented
              ariaLabel="Measure"
              value={measure}
              options={MEASURE_OPTIONS}
              onChange={setMeasure}
            />
          </LabeledControl>
        )}

        {type === WidgetType.reportSla && (
          <SelectField
            label="Window"
            value={weeks}
            onChange={(event) => setWeeks(event.target.value)}
          >
            {SLA_REPORT_WEEKS_OPTIONS.map((option) => (
              <option key={option} value={String(option)}>
                Last {option} weeks
              </option>
            ))}
          </SelectField>
        )}

        {isSlq && (
          <SlqEditor
            label="Query (blank = everything in scope)"
            value={q}
            onChange={setQ}
            probe={probe}
            suggestScope={projectId ? { project_id: projectId } : {}}
          />
        )}

        {type === WidgetType.slqCount && (
          <TextField
            label="Number caption (optional)"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="e.g. Open blockers"
            maxLength={60}
          />
        )}

        {type === WidgetType.slqList && (
          <SelectField
            label="Rows"
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
          >
            {[5, 10, 15, 20].map((option) => (
              <option key={option} value={String(option)}>
                {option}
              </option>
            ))}
          </SelectField>
        )}

        {type === WidgetType.viewCount && (
          <ViewSelect value={viewId === NONE ? "" : viewId} onChange={setViewId} />
        )}

        <SelectField
          label="Width"
          value={width}
          onChange={(event) => setWidth(event.target.value)}
          hint="Grid thirds — full-width suits charts, thirds suit counters"
        >
          {WIDTH_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </SelectField>

        {save.isError && !saveSlqError && (
          <ErrorText error={save.error} />
        )}
        {saveSlqError && (
          <p className="text-xs text-red-400">Query rejected on save: {saveSlqError.message}</p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!ready || save.isPending}>
            {save.isPending ? "Saving…" : widget ? "Save widget" : "Add widget"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** A labeled row for non-field controls (Segmented toggles). */
function LabeledControl({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-fg-secondary">{label}</span>
      <div>{children}</div>
    </div>
  );
}
