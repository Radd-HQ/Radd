import {
  BuiltinTarget,
  FieldAction,
  FieldBand,
  FieldScope,
  type BuiltinTargetValue,
  type FieldBandValue,
  type FieldMappingEntry,
  type PlanProblem,
} from "../../../lib/types";
import { SelectField } from "../../SelectField";
import { MappingSection, RowLabel } from "./MappingSection";

/** The Radd field types a "create" mapping can target (matches the server enum). */
const CREATE_TYPES = ["text", "select", "multi_select", "number", "date", "user"] as const;

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

const BANDS: [FieldBandValue, string, string][] = [
  [FieldBand.in_use, "Fields with data", ""],
  [
    FieldBand.unused,
    "Unused",
    "No issue has a value — nothing to import. Expand to map one anyway.",
  ],
  [
    FieldBand.noise,
    "Not worth mapping",
    "Board ordering keys, Jira's internal blobs, and org-wide defaults.",
  ],
  [
    FieldBand.builtin,
    "Handled natively",
    "Summary, status, assignee, etc. — imported as real Radd columns.",
  ],
];

/**
 * One row per inbound Jira field, banded (spec 100).
 *
 * Only `in_use` is expanded; the rest are collapsed AND already set to ignore,
 * each carrying the reason. On a live instance that is 337 fields down to about
 * a dozen worth deciding.
 */
export function FieldsTable({
  rows,
  existingKeys,
  existingOptions = {},
  problems,
  highlight = "",
  onChange,
}: {
  rows: FieldMappingEntry[];
  existingKeys: string[];
  /** Current option list per field key, so a MAP row can offer to extend it. */
  existingOptions?: Record<string, string[]>;
  problems: PlanProblem[];
  /** A field key or Jira id a run problem pointed at — ring it and open its band. */
  highlight?: string;
  onChange: (index: number, patch: Partial<FieldMappingEntry>) => void;
}) {
  const problemFor = new Map(problems.map((p) => [p.subject, p.message]));
  const isTarget = (r: FieldMappingEntry) =>
    Boolean(highlight) && (r.target_key === highlight || r.jira_id === highlight);
  return (
    <div className="flex flex-col gap-3">
      {BANDS.map(([band, title, hint]) => {
        const inBand = rows.filter((r) => r.band === band);
        return (
          <MappingSection
            key={band}
            title={title}
            hint={hint}
            count={inBand.length}
            // A problem inside a collapsed band would be invisible while the tab
            // badge insists something is wrong.
            defaultOpen={
              band === FieldBand.in_use ||
              inBand.some((r) => problemFor.has(r.jira_id) || isTarget(r))
            }
          >
            {inBand.map((entry) => (
              <FieldRow
                key={entry.jira_id}
                entry={entry}
                index={rows.indexOf(entry)}
                existingKeys={existingKeys}
                existingOptions={existingOptions}
                problem={problemFor.get(entry.jira_id)}
                highlighted={isTarget(entry)}
                onChange={onChange}
              />
            ))}
          </MappingSection>
        );
      })}
    </div>
  );
}

function FieldRow({
  entry,
  index,
  existingKeys,
  existingOptions,
  problem,
  highlighted = false,
  onChange,
}: {
  entry: FieldMappingEntry;
  index: number;
  existingKeys: string[];
  existingOptions: Record<string, string[]>;
  problem?: string;
  highlighted?: boolean;
  onChange: (index: number, patch: Partial<FieldMappingEntry>) => void;
}) {
  const set = (patch: Partial<FieldMappingEntry>) => onChange(index, patch);
  const actions =
    entry.band === FieldBand.builtin
      ? [FieldAction.builtin, FieldAction.native, FieldAction.ignore]
      : [FieldAction.create, FieldAction.map, FieldAction.native, FieldAction.ignore];

  return (
    <div
      className={"px-3 py-2 " + (highlighted ? "bg-amber-500/10 ring-1 ring-inset ring-amber-500/40" : "")}
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
          label=""
          ariaLabel={`${entry.jira_name}: what to do with this field`}
          className="w-40"
          value={entry.action}
          onChange={(e) => {
            const action = e.target.value as FieldMappingEntry["action"];
            if (action === FieldAction.create) {
              set({
                action,
                create_type: entry.create_type ?? "text",
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
            label=""
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
            label=""
            ariaLabel={`${entry.jira_name}: existing field to map into`}
            className="w-48"
            value={entry.target_key}
            onChange={(e) => set({ target_key: e.target.value })}
          >
            <option value="">Pick a field…</option>
            {existingKeys.map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </SelectField>
        )}

        {entry.action === FieldAction.create && (
          <>
            <input
              aria-label={`${entry.jira_name}: new field label`}
              value={entry.create_name}
              onChange={(e) => set({ create_name: e.target.value })}
              className="h-8 w-40 rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading outline-none focus-visible:outline-2 focus-visible:outline-focus"
            />
            <input
              aria-label={`${entry.jira_name}: new field key`}
              value={entry.target_key}
              onChange={(e) => set({ target_key: e.target.value.toLowerCase() })}
              className="h-8 w-40 rounded-md border border-strong bg-surface px-2.5 font-mono text-[12px] text-heading outline-none focus-visible:outline-2 focus-visible:outline-focus"
            />
            <SelectField
              label=""
              ariaLabel={`${entry.jira_name}: new field type`}
              className="w-32"
              value={entry.create_type ?? "text"}
              onChange={(e) => set({ create_type: e.target.value })}
            >
              {CREATE_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </SelectField>
            <SelectField
              label=""
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
      {/* Mapping into a select whose options do not cover the data: ADD them, or
          every value outside the list is dropped from the issues that carry it. */}
      {entry.action === FieldAction.map && (() => {
        const current = existingOptions[entry.target_key];
        if (!current?.length) return null;
        const known = new Set(current.map((v) => v.toLowerCase()));
        const missing = entry.observed_values.filter((v) => !known.has(v.toLowerCase()));
        if (missing.length === 0) return null;
        return (
          <label className="mt-1.5 flex items-start gap-2 pl-1 text-xs text-fg-secondary">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={entry.extend_options}
              onChange={(e) => set({ extend_options: e.target.checked })}
            />
            <span>
              Add {missing.length} missing option{missing.length === 1 ? "" : "s"} to{" "}
              <span className="font-mono text-fg">{entry.target_key}</span>
              <span
                className="block text-fg-faint"
                title={missing.join(", ")}
              >
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
      })()}
      {/* A select needs options; without an editor this was spec 90's dead end. */}
      {entry.action === FieldAction.create &&
        (entry.create_type === "select" || entry.create_type === "multi_select") && (
          <div className="mt-1.5 pl-1">
            <input
              aria-label={`${entry.jira_name}: options`}
              value={(entry.create_options ?? []).join(", ")}
              placeholder="comma-separated options"
              onChange={(e) =>
                set({
                  create_options: e.target.value
                    .split(",")
                    .map((v) => v.trim())
                    .filter(Boolean),
                })
              }
              className="h-8 w-full rounded-md border border-strong bg-surface px-2.5 text-[12px] text-heading outline-none focus-visible:outline-2 focus-visible:outline-focus"
            />
          </div>
        )}
      {problem && <p className="mt-1 text-xs text-red-400">{problem}</p>}
    </div>
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
