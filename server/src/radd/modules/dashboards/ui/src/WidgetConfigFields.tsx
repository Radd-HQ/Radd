/** The per-type half of the widget form: which scope and options each builtin type takes. */
import { SelectField, SlqField, TextField, ViewSelect } from "@radd/plugin-sdk";
import { CycleSelect, LabeledControl, ProjectSelect, Segmented } from "./controls";
import { PersonalWidgetType, ReportInterval, ReportMeasure, WidgetType, type ItemKindValue, type ReportIntervalValue, type ReportMeasureValue, type WidgetConfig } from "./types";
import {
  INTERVAL_OPTIONS, KIND_OPTIONS, MEASURE_OPTIONS, MEASURE_TYPES, OPTIONAL_PROJECT_TYPES, PROJECT_TYPES,
  SLA_WEEKS_OPTIONS, SLQ_LIST_ROWS, SLQ_TYPES, VELOCITY_LAST_OPTIONS,
} from "./widget-meta";

/** The form's working copy — strings for every select, one bag for every type. */
export interface ConfigDraft {
  project_id: string; interval: ReportIntervalValue; kind: ItemKindValue | ""; last: string;
  measure: ReportMeasureValue; cycle_id: string; weeks: string; q: string; label: string;
  limit: string; start: string; end: string; view_id: string;
}

export function draftOf(config: WidgetConfig = {}): ConfigDraft {
  return {
    project_id: config.project_id ?? "", interval: config.interval ?? ReportInterval.week, kind: config.kind ?? "",
    last: String(config.last ?? 5), measure: config.measure ?? ReportMeasure.count, cycle_id: config.cycle_id ?? "",
    weeks: String(config.weeks ?? 12), q: config.q ?? "", label: config.label ?? "", limit: String(config.limit ?? 10),
    start: config.start ?? "", end: config.end ?? "", view_id: config.view_id ?? "",
  };
}

/** The config a type's server-side schema takes; a plugin's type needs none of ours. */
export function configOf(type: string, d: ConfigDraft): WidgetConfig {
  switch (type) {
    case WidgetType.reportThroughput:
    case WidgetType.reportCfd: return { project_id: d.project_id, interval: d.interval };
    case WidgetType.reportTimeInState: return { project_id: d.project_id, kind: d.kind || null };
    case WidgetType.reportVelocity: return { last: Number(d.last), measure: d.measure };
    case WidgetType.reportBurnup: return { cycle_id: d.cycle_id, measure: d.measure };
    case WidgetType.reportSla: return { project_id: d.project_id || null, weeks: Number(d.weeks) };
    case WidgetType.slqCount: return { project_id: d.project_id || null, q: d.q, label: d.label.trim() || null };
    case WidgetType.slqList: return { project_id: d.project_id || null, q: d.q, limit: Number(d.limit) };
    case WidgetType.viewCount: return { view_id: d.view_id };
    case PersonalWidgetType.activity: return { project_id: d.project_id || null, start: d.start, end: d.end };
    default: return {};
  }
}

/** Whether the draft names everything its type requires (the SLQ half is checked live). */
export function isComplete(type: string, d: ConfigDraft): boolean {
  return (!PROJECT_TYPES.includes(type) || d.project_id !== "")
    && (type !== WidgetType.reportBurnup || d.cycle_id !== "")
    && (type !== WidgetType.viewCount || d.view_id !== "");
}

export function WidgetConfigFields({ type, draft, onChange, onSlqValidity }: {
  type: string;
  draft: ConfigDraft;
  onChange: (next: ConfigDraft) => void;
  onSlqValidity: (valid: boolean) => void;
}) {
  const set = <K extends keyof ConfigDraft>(key: K, value: ConfigDraft[K]) => onChange({ ...draft, [key]: value });
  const needsProject = PROJECT_TYPES.includes(type);
  return <>
    {(needsProject || OPTIONAL_PROJECT_TYPES.includes(type)) && (
      <ProjectSelect label={needsProject ? "Project" : "Project (optional)"} value={draft.project_id}
        onChange={(id) => set("project_id", id)} emptyLabel={needsProject ? null : "All projects"} emptyValue="" />
    )}
    {(type === WidgetType.reportThroughput || type === WidgetType.reportCfd) && (
      <LabeledControl label="Bucket interval">
        <Segmented ariaLabel="Bucket interval" value={draft.interval} options={INTERVAL_OPTIONS} onChange={(v) => set("interval", v)} />
      </LabeledControl>
    )}
    {type === WidgetType.reportTimeInState && (
      <SelectField label="Kind" value={draft.kind} onChange={(e) => set("kind", e.target.value as ItemKindValue | "")}>
        <option value="">All kinds</option>
        {KIND_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </SelectField>
    )}
    {type === WidgetType.reportVelocity && (
      <SelectField label="Cycles shown" value={draft.last} onChange={(e) => set("last", e.target.value)}>
        {VELOCITY_LAST_OPTIONS.map((n) => <option key={n} value={String(n)}>Last {n}</option>)}
      </SelectField>
    )}
    {type === WidgetType.reportBurnup && (
      <CycleSelect label="Cycle" value={draft.cycle_id} onChange={(id) => set("cycle_id", id)} emptyValue=""
        emptyLabel={null} datedOnly hint="Dated cycles only — a draft cycle has no window to chart" />
    )}
    {MEASURE_TYPES.includes(type) && (
      <LabeledControl label="Measure">
        <Segmented ariaLabel="Measure" value={draft.measure} options={MEASURE_OPTIONS} onChange={(v) => set("measure", v)} />
      </LabeledControl>
    )}
    {type === WidgetType.reportSla && (
      <SelectField label="Window" value={draft.weeks} onChange={(e) => set("weeks", e.target.value)}>
        {SLA_WEEKS_OPTIONS.map((n) => <option key={n} value={String(n)}>Last {n} weeks</option>)}
      </SelectField>
    )}
    {SLQ_TYPES.includes(type) && (
      <SlqField label="Query (blank = everything in scope)" value={draft.q} onChange={(q) => set("q", q)}
        projectId={draft.project_id || undefined} onValidity={onSlqValidity} />
    )}
    {type === PersonalWidgetType.activity && <div className="flex gap-3">
      <TextField label="From date (optional)" type="date" value={draft.start} onChange={(e) => set("start", e.target.value)} />
      <TextField label="To date (optional)" type="date" min={draft.start} value={draft.end} onChange={(e) => set("end", e.target.value)} />
    </div>}
    {type === WidgetType.slqCount && (
      <TextField label="Number caption (optional)" value={draft.label} onChange={(e) => set("label", e.target.value)}
        placeholder="e.g. Open blockers" maxLength={60} />
    )}
    {type === WidgetType.slqList && (
      <SelectField label="Rows" value={draft.limit} onChange={(e) => set("limit", e.target.value)}>
        {SLQ_LIST_ROWS.map((n) => <option key={n} value={String(n)}>{n}</option>)}
      </SelectField>
    )}
    {type === WidgetType.viewCount && <ViewSelect value={draft.view_id} onChange={(id) => set("view_id", id)} />}
  </>;
}
