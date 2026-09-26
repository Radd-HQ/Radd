import { memo, useEffect, useState } from "react";
import { SelectField } from "@radd/plugin-sdk";
import { MAPPING_INPUT_CLASS, RowLabel } from "./MappingSection";
import {
  BuiltinTarget,
  CreateFieldType,
  FieldAction,
  FieldBand,
  FieldScope,
  type BuiltinTargetValue,
  type FieldMappingEntry,
} from "./plan-types";
import { ValueMappings } from "./ValueMappings";

const ACTION_LABEL: Record<string, string> = {
  [FieldAction.ignore]: "Ignore",
  [FieldAction.map]: "Map to field",
  [FieldAction.create]: "Create field",
  [FieldAction.native]: "Map to feature",
  [FieldAction.builtin]: "Native (handled)",
};

/** Native Radd targets a field can feed. */
const BUILTIN_TARGETS: [BuiltinTargetValue, string][] = [
  [BuiltinTarget.team, "Team"],
  [BuiltinTarget.status, "Status / State"],
  [BuiltinTarget.watchers, "Watchers"],
  [BuiltinTarget.parent, "Parent / Epic"],
  [BuiltinTarget.assignee, "Assignee"],
  [BuiltinTarget.labels, "Labels"],
  [BuiltinTarget.cycle, "Cycle (sprint)"],
  [BuiltinTarget.priority, "Priority"],
  [BuiltinTarget.start_date, "Start date"],
  [BuiltinTarget.target_date, "Target date"],
  [BuiltinTarget.points, "Story points"],
];

const SELECT_TYPES: readonly string[] = [CreateFieldType.select, CreateFieldType.multi_select];

/** One inbound Jira field: what to do with it, and — for a map/create — its values. */
export const FieldRow = memo(function FieldRow({
  entry,
  index,
  existingKeys,
  existingOptions,
  fieldLabels,
  nativeOptions,
  problem,
  highlighted = false,
  onChange,
}: {
  entry: FieldMappingEntry;
  index: number;
  existingKeys: string[];
  existingOptions: Record<string, string[]>;
  fieldLabels: Record<string, string>;
  nativeOptions: Record<string, string[]>;
  problem?: string;
  highlighted?: boolean;
  onChange: (index: number, patch: Partial<FieldMappingEntry>) => void;
}) {
  const set = (patch: Partial<FieldMappingEntry>) => onChange(index, patch);
  const actions =
    entry.band === FieldBand.builtin
      ? [FieldAction.builtin, FieldAction.native, FieldAction.ignore]
      : [FieldAction.create, FieldAction.map, FieldAction.native, FieldAction.ignore];
  const translates =
    entry.action === FieldAction.map || entry.action === FieldAction.create ||
    (entry.action === FieldAction.native && entry.builtin_target === BuiltinTarget.team);

  return (
    <div
      className={"px-3 py-2 " + (highlighted ? "bg-status-warning/10 ring-1 ring-inset ring-status-warning/40" : "")}
    >
      <div className="flex flex-wrap items-center gap-2">
        <RowLabel
          value={entry.jira_name || entry.jira_id}
          detail={
            entry.samples.length
              ? `${entry.jira_id} · e.g. ${entry.samples.slice(0, 3).join(", ")}`
              : entry.jira_id
          }
          reason={entry.band_reason}
        />
        <SelectField
          label="Action"
          ariaLabel={`${entry.jira_name}: what to do with this field`}
          className="w-40"
          value={entry.action}
          onChange={(e) => {
            const action = e.target.value as FieldMappingEntry["action"];
            if (action === FieldAction.create) {
              set({
                action,
                create_type: entry.create_type ?? CreateFieldType.text,
                create_name: entry.create_name || entry.jira_name,
                target_key: entry.target_key || slugify(entry.jira_name),
              });
            } else if (action === FieldAction.native) {
              set({ action, builtin_target: entry.builtin_target ?? BuiltinTarget.team });
            } else {
              set({ action });
            }
          }}
        >
          {actions.map((action) => (
            <option key={action} value={action}>
              {ACTION_LABEL[action]}
            </option>
          ))}
        </SelectField>

        {entry.action === FieldAction.native && (
          <SelectField
            label="RADD feature"
            ariaLabel={`${entry.jira_name}: which Radd feature`}
            className="w-44"
            value={entry.builtin_target ?? ""}
            onChange={(e) => set({ builtin_target: e.target.value as BuiltinTargetValue })}
          >
            {BUILTIN_TARGETS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </SelectField>
        )}

        {entry.action === FieldAction.map && (
          <SelectField
            label="Existing RADD field"
            ariaLabel={`${entry.jira_name}: existing field to map into`}
            className="w-48"
            value={entry.target_key}
            onChange={(e) => set({ target_key: e.target.value })}
          >
            <option value="">Pick a field…</option>
            {existingKeys.map((key) => (
              <option key={key} value={key}>
                {fieldLabels[key] ?? key}
              </option>
            ))}
          </SelectField>
        )}

        {entry.action === FieldAction.create && (
          <>
            <label className="flex flex-col gap-1 text-xs text-fg-secondary">Field label
            <input
              aria-label={`${entry.jira_name}: new field label`}
              value={entry.create_name}
              onChange={(e) => set({ create_name: e.target.value })}
              className={`w-40 text-[13px] ${MAPPING_INPUT_CLASS}`}
            />
            </label>
            <label className="flex flex-col gap-1 text-xs text-fg-secondary">Field key
            <input
              aria-label={`${entry.jira_name}: new field key`}
              value={entry.target_key}
              onChange={(e) => set({ target_key: e.target.value.toLowerCase() })}
              className={`w-40 font-mono text-[12px] ${MAPPING_INPUT_CLASS}`}
            />
            </label>
            <SelectField
              label="Field type"
              ariaLabel={`${entry.jira_name}: new field type`}
              className="w-32"
              value={entry.create_type ?? CreateFieldType.text}
              onChange={(e) => set({ create_type: e.target.value })}
            >
              {Object.values(CreateFieldType).map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </SelectField>
            <SelectField
              label="Scope"
              ariaLabel={`${entry.jira_name}: new field scope`}
              className="w-28"
              value={entry.create_scope}
              onChange={(e) =>
                set({ create_scope: e.target.value as FieldMappingEntry["create_scope"] })
              }
            >
              <option value={FieldScope.global}>Global</option>
              <option value={FieldScope.project}>Project</option>
            </SelectField>
          </>
        )}
      </div>
      {entry.action === FieldAction.map && (
        <MissingOptions entry={entry} current={existingOptions[entry.target_key]} onChange={set} />
      )}
      {/* A select needs options, so creating one offers an editor for them. */}
      {entry.action === FieldAction.create && SELECT_TYPES.includes(entry.create_type ?? "") && (
        <div className="mt-1.5 pl-1">
          <CommaOptions values={entry.create_options ?? []} label={`${entry.jira_name}: options`} onChange={create_options => set({ create_options })} />
        </div>
      )}
      {translates && <ValueMappings
        values={entry.observed_values} targets={entry.action === FieldAction.native ? nativeOptions[entry.builtin_target ?? ""] ?? [] : existingOptions[entry.target_key] ?? entry.create_options ?? []}
        mapping={entry.value_map} onChange={value_map => set({ value_map })} />}
      {problem && <p className="mt-1 text-xs text-status-danger-ink">{problem}</p>}
    </div>
  );
});

/** Mapping into a select whose options do not cover the data: ADD them, or every
 * value outside the list is dropped from the issues that carry it. */
function MissingOptions({ entry, current, onChange }: {
  entry: FieldMappingEntry;
  current: string[] | undefined;
  onChange: (patch: Partial<FieldMappingEntry>) => void;
}) {
  if (!current?.length) return null;
  const known = new Set(current.map((v) => v.toLowerCase()));
  const missing = entry.observed_values.map(v => entry.value_map[v] ?? v).filter((v) => !known.has(v.toLowerCase()));
  if (missing.length === 0) return null;
  return (
    <label className="mt-1.5 flex items-start gap-2 pl-1 text-xs text-fg-secondary">
      <input
        type="checkbox"
        className="mt-0.5"
        checked={entry.extend_options}
        onChange={(e) => onChange({ extend_options: e.target.checked })}
      />
      <span>
        Add {missing.length} missing option{missing.length === 1 ? "" : "s"} to{" "}
        <span className="font-mono text-fg">{entry.target_key}</span>
        <span className="block text-fg-faint" title={missing.join(", ")}>
          {missing.slice(0, 6).join(", ")}
          {missing.length > 6 && ` and ${missing.length - 6} more`}
          {" — "}
          {entry.extend_options
            ? "existing options are kept; rollback restores the list"
            : "unticked, these values are DROPPED from the issues that use them"}
        </span>
      </span>
    </label>
  );
}

function slugify(name: string): string {
  const lowered = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const safe = lowered || "field";
  return (/^[a-z]/.test(safe) ? safe : `f_${safe}`).slice(0, 50);
}

function CommaOptions({ values, label, onChange }: { values: string[]; label: string; onChange: (values: string[]) => void }) {
  const [text, setText] = useState(values.join(", "));
  const parse = (value: string) => value.split(",").map(v => v.trim()).filter(Boolean);
  useEffect(() => {
    if (JSON.stringify(parse(text)) !== JSON.stringify(values)) setText(values.join(", "));
  }, [values]);
  return <label className="flex flex-col gap-1 text-xs text-fg-secondary">Allowed options (comma-separated)
    <input aria-label={label} value={text} onChange={e => { setText(e.target.value); onChange(parse(e.target.value)); }}
      className="h-8 rounded border border-strong bg-surface px-2 text-heading" />
  </label>;
}
