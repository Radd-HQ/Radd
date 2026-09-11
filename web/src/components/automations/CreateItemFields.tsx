import { OptionTextField } from "../DirectoryChoices";
import { OptionResource } from "../../lib/queries/options";
import { ProjectSelect } from "../projects/ProjectSelect";
/**
 * The full create-item form (spec 116).
 *
 * It offered project, title, description and priority — so an automation could
 * only file a stub someone then finished by hand, which is most of the work it
 * was supposed to save. Everything an issue has is here now, including custom
 * fields by registry key.
 *
 * Names, not ids, throughout: an automation is written against a project's
 * vocabulary ("In Review", "Bug", an email) and keeps working when the
 * underlying rows are recreated. The server resolves them at APPLY time and
 * skip-logs with the name when one has gone, rather than silently dropping it.
 */
import { CollapsibleCard } from "../CollapsibleCard";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import { TokenMultiSelect } from "../TokenMultiSelect";
import type { PickerData } from "./ActionsBuilder";

type Params = Record<string, unknown>;

interface CreateItemFieldsProps {
  params: Params;
  pickers: PickerData;
  onChange: (params: Params) => void;
}

const KINDS = ["issue", "epic", "subtask"];
const PRIORITIES = ["low", "normal", "high", "blocker"];

export function CreateItemFields({ params, pickers, onChange }: CreateItemFieldsProps) {
  const set = (patch: Params) => onChange({ ...params, ...patch });
  const text = (key: string) => String(params[key] ?? "");

  return (
    <div className="flex flex-col gap-2">
      <ProjectSelect label="Project" valueBy="key" value={text("project")}
        onChange={project => set({ project })} hint="Where the new issue is filed." />
      <TextField
        label="Title"
        value={text("title")}
        onChange={(event) => set({ title: event.target.value })}
        placeholder="Follow up on {{item.key}}"
        required
      />
      <TextField
        label="Description"
        value={text("description")}
        onChange={(event) => set({ description: event.target.value })}
        placeholder="Raised by {{actor.name}} on {{event_type}}"
      />

      <CollapsibleCard title="Classification" count={countSet(params, ["kind", "type", "state", "priority"])}>
        <div className="flex flex-col gap-2">
          <SelectField
            label="Kind"
            value={text("kind")}
            onChange={(event) => set({ kind: event.target.value || null })}
            hint="A subtask needs a parent; an epic must not have one."
          >
            <option value="">Issue (default)</option>
            {KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Issue type"
            value={text("type")}
            onChange={(event) => set({ type: event.target.value || null })}
            placeholder="Bug"
            hint="Name, resolved in the target project. Empty = its default type."
          />
          <OptionTextField resource={OptionResource.state} label="State" value={text("state")}
            onChange={state => set({ state: state || null })} hint="Empty = the project's first state. Names resolve in the target project." />
          <SelectField
            label="Priority"
            value={text("priority")}
            onChange={(event) => set({ priority: event.target.value || null })}
          >
            <option value="">Normal</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </SelectField>
        </div>
      </CollapsibleCard>

      <CollapsibleCard
        title="People and planning"
        count={countSet(params, ["assignee", "reporter", "team", "cycle", "release", "parent", "estimate_points", "start_date", "target_date"])}
      >
        <div className="flex flex-col gap-2">
          <TextField
            label="Assignee"
            value={text("assignee")}
            onChange={(event) => set({ assignee: event.target.value || null })}
            placeholder="alice@example.com — or {{actor.email}}"
          />
          <TextField
            label="Reporter"
            value={text("reporter")}
            onChange={(event) => set({ reporter: event.target.value || null })}
            placeholder="Defaults to whoever the automation acts as"
          />
          <TextField
            label="Team"
            value={text("team")}
            onChange={(event) => set({ team: event.target.value || null })}
            placeholder="Platform"
          />
          <TextField
            label="Cycle"
            value={text("cycle")}
            onChange={(event) => set({ cycle: event.target.value || null })}
          />
          <TextField
            label="Release"
            value={text("release")}
            onChange={(event) => set({ release: event.target.value || null })}
            placeholder="0.22.0"
          />
          <TextField
            label="Parent"
            value={text("parent")}
            onChange={(event) => set({ parent: event.target.value || null })}
            placeholder="TD-42 — or {{item.key}} to nest under the triggering issue"
          />
          <TextField
            label="Estimate (points)"
            value={text("estimate_points")}
            onChange={(event) =>
              set({ estimate_points: event.target.value === "" ? null : Number(event.target.value) })
            }
            type="number"
          />
          <TextField
            label="Start date"
            value={text("start_date")}
            onChange={(event) => set({ start_date: event.target.value || null })}
            placeholder="2026-08-06, or today+3d"
            hint="ISO date, or the same relative words SLQ uses."
          />
          <TextField
            label="Target date"
            value={text("target_date")}
            onChange={(event) => set({ target_date: event.target.value || null })}
            placeholder="today+14d"
          />
        </div>
      </CollapsibleCard>

      <CollapsibleCard
        title="Labels and custom fields"
        count={((params.labels as string[]) ?? []).length + Object.keys((params.custom_fields as Params) ?? {}).length}
      >
        <div className="flex flex-col gap-2">
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-medium uppercase tracking-wide text-fg-secondary">
              Labels
            </span>
            <TokenMultiSelect
              value={(params.labels as string[]) ?? []}
              onChange={(labels) => set({ labels })}
              options={pickers.labelNames.map((value) => ({ value, label: value }))}
              placeholder="Add a label…"
              ariaLabel="Labels"
              allowCreate
            />
          </div>
          <CustomFieldRows
            value={(params.custom_fields as Params) ?? {}}
            fields={pickers.fields.map((field) => field.key)}
            onChange={(custom_fields) => set({ custom_fields })}
          />
        </div>
      </CollapsibleCard>
    </div>
  );
}

function countSet(params: Params, keys: string[]): number {
  return keys.filter((key) => params[key] !== undefined && params[key] !== null && params[key] !== "")
    .length;
}

/** Key/value rows over the project's custom-field registry. Values are stored
 * raw and validated by the items service against the TARGET project's
 * definitions at apply time — the same path a human create takes, rather than a
 * second validator here that could disagree with it. */
function CustomFieldRows({
  value,
  fields,
  onChange,
}: {
  value: Params;
  fields: string[];
  onChange: (next: Params) => void;
}) {
  const entries = Object.entries(value);
  const unused = fields.filter((key) => !(key in value));
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wide text-fg-secondary">
        Custom fields
      </span>
      {entries.map(([key, current]) => (
        <div key={key} className="flex items-end gap-1.5">
          <TextField
            label={key}
            value={String(current ?? "")}
            onChange={(event) => onChange({ ...value, [key]: event.target.value })}
            className="flex-1"
          />
          <button
            type="button"
            onClick={() => {
              const next = { ...value };
              delete next[key];
              onChange(next);
            }}
            aria-label={`Remove ${key}`}
            className="mb-1 rounded px-1.5 py-1 text-xs text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
          >
            ×
          </button>
        </div>
      ))}
      {unused.length > 0 && (
        <SelectField
          label=""
          value=""
          onChange={(event) => {
            if (event.target.value) onChange({ ...value, [event.target.value]: "" });
          }}
        >
          <option value="">Add a custom field…</option>
          {unused.map((key) => (
            <option key={key} value={key}>
              {key}
            </option>
          ))}
        </SelectField>
      )}
    </div>
  );
}
