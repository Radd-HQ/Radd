/** Forms for the named condition nodes. `from`/`to` carry an explicit MODE: an empty list is also what a
 * half-filled form produces, and reading it as "any" fires on changes nobody meant. */
import type React from "react";
import { OptionNameValues, OptionSelect } from "@radd/plugin-sdk";
import { OptionResource, type OptionResourceValue } from "./options";
import { CheckField } from "./controls";
import type { OperatorInfo } from "./types";
import { TextField } from "@radd/plugin-sdk";
import { SelectField } from "@radd/plugin-sdk";
import { TokenMultiSelect } from "@radd/plugin-sdk";

/** A label above a control that has none of its own. */
function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium uppercase tracking-wide text-fg-secondary">
        {label}
      </span>
      {children}
    </div>
  );
}

const MODE_ANY = "any";
const MODE_SPECIFIC = "specific";
const MODE_EMPTY = "empty";

const MODES = [
  { value: MODE_ANY, label: "Any value" },
  { value: MODE_SPECIFIC, label: "One of these…" },
  { value: MODE_EMPTY, label: "Empty / not set" },
];

type Params = Record<string, unknown>;

interface SideProps {
  legend: string;
  hint: string;
  mode: string;
  values: string[];
  suggestions: string[];
  resource?: OptionResourceValue;
  onChange: (mode: string, values: string[]) => void;
}

function ChangeSide({ legend, hint, mode, values, suggestions, resource, onChange }: SideProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <SelectField
        label={legend}
        value={mode}
        onChange={(event) => onChange(event.target.value, values)}
        hint={hint}
      >
        {MODES.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </SelectField>
      {mode === MODE_SPECIFIC && (resource
        ? <OptionNameValues resource={resource} label={`${legend} values`} value={values} onChange={values => onChange(mode, values)} />
        : <TokenMultiSelect
          value={values}
          onChange={(next) => onChange(mode, next)}
          options={suggestions.map((value) => ({ value, label: value }))}
          placeholder="Add a value…"
          ariaLabel={`${legend} values`}
          allowCreate
        />
      )}
    </div>
  );
}

interface FieldChangedProps {
  params: Params;
  /** Field names the picker offers — builtins plus custom-field keys. */
  fieldNames: string[];
  /** Fields the upstream trigger's REAL events have been seen changing, from
   * `GET /automations/samples/events`. Offered first, because the full list
   * includes fields this trigger's diff never names. */
  observedFields?: string[];
  /** Values to suggest for the currently-chosen field (state names, priorities…). */
  valueSuggestions: string[];
  onChange: (params: Params) => void;
}

export function FieldChangedFields({
  params,
  fieldNames,
  observedFields = [],
  valueSuggestions,
  onChange,
}: FieldChangedProps) {
  const set = (patch: Params) => onChange({ ...params, ...patch });
  return (
    <div className="flex flex-col gap-2">
      <SelectField
        label="Field"
        value={String(params.field ?? "")}
        onChange={(event) => set({ field: event.target.value })}
        hint="Reads the event's own diff, so it matches the TRANSITION — not an issue that was already in the target state."
      >
        {/* Fields SEEN changing first: a field the diff never names makes a condition that is always false. */}
        {observedFields.length > 0 && (
          <optgroup label="Seen changing on this trigger">
            {observedFields.map((name) => (
              <option key={`seen-${name}`} value={name}>
                {name}
              </option>
            ))}
          </optgroup>
        )}
        <optgroup label={observedFields.length > 0 ? "Every field" : "Fields"}>
          {fieldNames.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </optgroup>
      </SelectField>
      <ChangeSide
        legend="From"
        hint="What it changed away from."
        mode={String(params.from_mode ?? MODE_ANY)}
        values={(params.from_values as string[]) ?? []}
        suggestions={valueSuggestions}
        resource={params.field === "state" ? OptionResource.state : params.field === "release" ? OptionResource.release : undefined}
        onChange={(from_mode, from_values) => set({ from_mode, from_values })}
      />
      <ChangeSide
        legend="To"
        hint="What it changed into. Several values means any of them."
        mode={String(params.to_mode ?? MODE_ANY)}
        values={(params.to_values as string[]) ?? []}
        suggestions={valueSuggestions}
        resource={params.field === "state" ? OptionResource.state : params.field === "release" ? OptionResource.release : undefined}
        onChange={(to_mode, to_values) => set({ to_mode, to_values })}
      />
    </div>
  );
}

export function ChangedByFields({
  params,
  canChoosePeople,
  onChange,
}: {
  params: Params;
  canChoosePeople: boolean;
  onChange: (params: Params) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Labelled label="People">
        <OptionNameValues resource={OptionResource.user} label="People" canBrowse={canChoosePeople}
          value={(params.users as string[]) ?? []} onChange={users => onChange({ ...params, users })} />
      </Labelled>
      <CheckField label="Invert — true when it was NOT one of them" checked={Boolean(params.negate)} onChange={(checked) => onChange({ ...params, negate: checked })} />
    </div>
  );
}

/** Who a membership gate asks about (the server's `GatePerson`): a role on the issue, the event's
 *  actor, or — typed or browsed — an email. */
export const GATE_PERSON_PRESETS = [
  { value: "reporter", label: "Its reporter", hint: "" },
  { value: "assignee", label: "Its assignee", hint: "" },
  { value: "actor", label: "Whoever made the change", hint: "" },
];

/** "Person is in team" (RADD-1498): the person, the teams (names), and the invert. */
export function PersonInTeamFields({
  params,
  canChoosePeople,
  onChange,
}: {
  params: Params;
  canChoosePeople: boolean;
  onChange: (params: Params) => void;
}) {
  return (
    <div className="flex flex-col gap-2" data-person-in-team>
      <OptionSelect resource={OptionResource.user} label="Person" value={String(params.person ?? "reporter")}
        canBrowse={canChoosePeople} presets={GATE_PERSON_PRESETS}
        onChange={(person) => onChange({ ...params, person })} />
      <Labelled label="Is on one of these teams">
        <OptionNameValues resource={OptionResource.team} label="Teams"
          value={(params.teams as string[]) ?? []} onChange={(teams) => onChange({ ...params, teams })} />
      </Labelled>
      <p className="text-xs text-fg-muted">Team membership counts the people a directory group carries into the team.</p>
      <CheckField label="Invert — true when they are NOT on any of them" checked={Boolean(params.negate)} onChange={(checked) => onChange({ ...params, negate: checked })} />
    </div>
  );
}

const CATEGORIES = ["triage", "backlog", "todo", "in_progress", "done", "canceled"];

export function StateCategoryFields({
  params,
  onChange,
}: {
  params: Params;
  onChange: (params: Params) => void;
}) {
  return (
    <Labelled label="Category is one of">
      <TokenMultiSelect
        value={(params.categories as string[]) ?? []}
        onChange={(categories) => onChange({ ...params, categories })}
        options={CATEGORIES.map((value) => ({ value, label: value }))}
        placeholder="Add a category…"
        ariaLabel="Category is one of"
      />
    </Labelled>
  );
}

/** RADD-1248: "Comment is" — a root or a reply, public or internal. Asked of
 * a comment event on either surface; anything else answers false. */
export function CommentGateFields({
  params,
  onChange,
}: {
  params: Params;
  onChange: (params: Params) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <SelectField
        label="Thread"
        value={String(params.thread ?? "any")}
        onChange={(event) => onChange({ ...params, thread: event.target.value })}
        hint="A reply sits under another comment; a root starts a thread."
      >
        <option value="any">Any comment</option>
        <option value="root">A thread root</option>
        <option value="reply">A reply</option>
      </SelectField>
      <SelectField
        label="Visibility"
        value={String(params.visibility ?? "any")}
        onChange={(event) => onChange({ ...params, visibility: event.target.value })}
      >
        <option value="any">Public or internal</option>
        <option value="public">Public</option>
        <option value="internal">Internal</option>
      </SelectField>
    </div>
  );
}

/** RADD-1248: "Page is in space" — for page events and page comments alike;
 * an event about no page answers false. Slugs, the thing people read in the
 * address bar; the directory supplies them as options. */
export function PageSpaceFields({
  params,
  onChange,
}: {
  params: Params;
  onChange: (params: Params) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Labelled label={params.negate ? "Space is NOT one of" : "Space is one of"}>
        <OptionNameValues resource={OptionResource.space}
          label="Space is one of"
          value={(params.spaces as string[]) ?? []}
          onChange={(next) => onChange({ ...params, spaces: next })}
        />
      </Labelled>
      <CheckField label="Invert — every space except these" checked={Boolean(params.negate)} onChange={(checked) => onChange({ ...params, negate: checked })} />
    </div>
  );
}

/** "Event value is" (RADD-1265) — the one open-ended gate: a dotted path into
 * the event payload, an operator, a value. The paths offered are the ones REAL
 * recent events of the upstream trigger carried, so the picker cannot suggest
 * an address nothing ever emits. */
export function PayloadGateFields({
  params,
  operators,
  paths,
  onChange,
}: {
  params: Params;
  operators: OperatorInfo[];
  paths: string[];
  onChange: (params: Params) => void;
}) {
  const operator = String(params.operator ?? "eq");
  const info = operators.find((entry) => entry.key === operator);
  const needsValue = info?.needs_value ?? true;
  const listValue = info?.list_value ?? false;
  const value = params.value;
  const listId = "payload-gate-paths";
  return (
    <div className="flex flex-col gap-2">
      <TextField
        label="Value at"
        value={String(params.path ?? "")}
        onChange={(event) => onChange({ ...params, path: event.target.value })}
        placeholder="item.state.name"
        list={listId}
        hint="A dotted path into the event's payload. Lists fan out, so `item.labels contains urgent` reads naturally."
      />
      <datalist id={listId}>
        {paths.map((path) => (
          <option key={path} value={path} />
        ))}
      </datalist>
      <SelectField
        label="Test"
        value={operator}
        onChange={(event) => {
          const next = event.target.value;
          const nextInfo = operators.find((entry) => entry.key === next);
          onChange({
            ...params,
            operator: next,
            value: nextInfo?.list_value ? (Array.isArray(value) ? value : []) : Array.isArray(value) ? "" : value,
          });
        }}
      >
        {operators.map((entry) => (
          <option key={entry.key} value={entry.key}>
            {entry.label}
          </option>
        ))}
      </SelectField>
      {needsValue && listValue && (
        <Labelled label="Values">
          <TokenMultiSelect
            value={Array.isArray(value) ? (value as string[]) : []}
            onChange={(next) => onChange({ ...params, value: next })}
            options={[]}
            placeholder="Add a value…"
            ariaLabel="Values"
            allowCreate
          />
        </Labelled>
      )}
      {needsValue && !listValue && (
        <TextField
          label="Value"
          value={Array.isArray(value) ? "" : String(value ?? "")}
          onChange={(event) => onChange({ ...params, value: event.target.value })}
          placeholder="Done"
        />
      )}
      <CheckField label="Invert — true when the test does NOT hold" checked={Boolean(params.negate)} onChange={(checked) => onChange({ ...params, negate: checked })} />
    </div>
  );
}

/** "Project is" (RADD-1267) — the one way to narrow a NON-item event (a
 * release, a form, a cycle) by project; a filter can only see items. Reads the
 * project ref the kernel wrote on the event, or the item's own. */
export function ProjectGateFields({
  params,
  onChange,
}: {
  params: Params;
  onChange: (params: Params) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Labelled label={params.negate ? "Project is NOT one of" : "Project is one of"}>
        <TokenMultiSelect
          value={(params.projects as string[]) ?? []}
          onChange={(projects) => onChange({ ...params, projects: projects.map((key) => key.trim().toUpperCase()) })}
          options={[]}
          placeholder="Add a project key…"
          ariaLabel="Project is one of"
          allowCreate
        />
      </Labelled>
      <CheckField label="Invert — true when the project is NOT one of them" checked={Boolean(params.negate)} onChange={(checked) => onChange({ ...params, negate: checked })} />
    </div>
  );
}
