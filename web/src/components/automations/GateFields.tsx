import { OptionNameValues } from "../DirectoryChoices";
import { OptionResource, type OptionResourceValue } from "../../lib/queries/options";
/**
 * Forms for the concrete condition nodes (spec 116 revision).
 *
 * Each is one named test with named fields, replacing the abstract
 * subject/operator/value tree. "Field changed / Field: State / From: Any value /
 * To: In Review" is readable without knowing the model; the tree was not.
 *
 * `from` and `to` carry an explicit MODE rather than "empty list means any",
 * because an empty list is also what a half-filled form produces — and treating
 * that as "match everything" is how an automation fires on changes nobody meant
 * to catch.
 */
import type React from "react";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { pageSpacesQuery } from "../../lib/queries";
import { api, errorMessage } from "../../lib/api";
import { ApiPath } from "../../lib/constants";
import type { ScriptRunOutcome } from "../../lib/types";
import { Button } from "../Button";
import { PythonEditor } from "../scripts/PythonEditor";
import type { OperatorInfo } from "../../lib/types";
import { TextField } from "../TextField";
import { SelectField } from "../SelectField";
import { TokenMultiSelect } from "../TokenMultiSelect";

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
        hint="Reads the event's own diff, so it matches the TRANSITION — not an item that was already in the target state."
      >
        {/* Fields the trigger's real events have been SEEN changing come first
            (RADD-921). The full list below includes every custom-field key,
            some of which the diff never names — a condition on one of those can
            only ever be false, and looks exactly like one that has not matched
            yet. */}
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
      <label className="flex w-fit cursor-pointer items-center gap-2 text-[13px] text-fg">
        <input
          type="checkbox"
          checked={Boolean(params.negate)}
          onChange={(event) => onChange({ ...params, negate: event.target.checked })}
          className="size-3.5 cursor-pointer accent-[var(--accent-fill)]"
        />
        Invert — true when it was NOT one of them
      </label>
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
  const spaces = useQuery(pageSpacesQuery());
  const options = (spaces.data ?? []).map((space) => ({ value: space.slug, label: `${space.name} (${space.slug})` }));
  return (
    <div className="flex flex-col gap-2">
      <Labelled label={params.negate ? "Space is NOT one of" : "Space is one of"}>
        <TokenMultiSelect
          value={(params.spaces as string[]) ?? []}
          onChange={(next) => onChange({ ...params, spaces: next })}
          options={options}
          placeholder="Add a space…"
          ariaLabel="Space is one of"
        />
      </Labelled>
      <label className="flex items-center gap-2 text-xs text-fg-secondary">
        <input
          type="checkbox"
          checked={Boolean(params.negate)}
          onChange={(event) => onChange({ ...params, negate: event.target.checked })}
        />
        Invert — every space except these
      </label>
    </div>
  );
}

/** The AI classifier (contributed by the AI module). Its answers ARE its output
 * ports, which is why they are edited here rather than in a generated form: the
 * canvas has to redraw the node as they change. */
export function AiClassifyFields({
  params,
  onChange,
}: {
  params: Params;
  onChange: (params: Params) => void;
}) {
  const answers = (params.answers as string[]) ?? [];
  return (
    <div className="flex flex-col gap-2">
      <TextField
        label="Question"
        value={String(params.prompt ?? "")}
        onChange={(event) => onChange({ ...params, prompt: event.target.value })}
        placeholder="Is this a bug report, a feature request, or a question?"
        hint="Asked once per run, with the item summaries appended."
      />
      <Labelled label="Possible answers">
        <TokenMultiSelect
          value={answers}
          onChange={(next) => onChange({ ...params, answers: next })}
          options={[]}
          placeholder="Add an answer…"
          ariaLabel="Possible answers"
          allowCreate
        />
      </Labelled>
      <p className="text-xs text-fg-secondary">
        Each answer becomes an output port on the node. The model is constrained to these, so it
        cannot invent a branch that does not exist — and an <strong>unavailable</strong> port
        catches the case where the provider is down, rather than the run stopping silently.
      </p>

      <Labelled label="What the model sees">
        <div className="flex flex-col gap-1">
          {[
            { key: "fields", label: "Fields — type, state, priority, assignee, labels, custom fields", on: true },
            { key: "description", label: "Description (in full)", on: true },
            { key: "comments", label: "Comments (all of them)", on: false },
            { key: "worklogs", label: "Logged time", on: false },
          ].map((section) => {
            const include = (params.include as Record<string, boolean>) ?? {};
            const checked = include[section.key] ?? section.on;
            return (
              <label
                key={section.key}
                className="flex cursor-pointer items-start gap-2 text-[13px] text-fg"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(event) =>
                    onChange({
                      ...params,
                      include: { ...include, [section.key]: event.target.checked },
                    })
                  }
                  className="mt-0.5 size-3.5 cursor-pointer accent-[var(--accent-fill)]"
                />
                <span>{section.label}</span>
              </label>
            );
          })}
        </div>
      </Labelled>
      <p className="text-xs text-fg-secondary">
        Sent to your configured AI provider. Reads run as the automation&rsquo;s identity, so the
        prompt can only contain what it could already see. Items are sent <em>whole</em> — nothing
        is clipped mid-sentence. If a run exceeds the prompt budget, later items are left out and
        the prompt says how many, so the model knows it is answering about a sample. The budget is
        the <code>RADD_AI_AUTOMATION_CONTEXT_CHARS</code> setting; size it to your model.
      </p>
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
      <label className="flex w-fit cursor-pointer items-center gap-2 text-[13px] text-fg">
        <input
          type="checkbox"
          checked={Boolean(params.negate)}
          onChange={(event) => onChange({ ...params, negate: event.target.checked })}
          className="size-3.5 cursor-pointer accent-[var(--accent-fill)]"
        />
        Invert — true when the test does NOT hold
      </label>
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
      <label className="flex items-center gap-2 text-xs text-fg-secondary">
        <input
          type="checkbox"
          checked={Boolean(params.negate)}
          onChange={(event) => onChange({ ...params, negate: event.target.checked })}
          className="size-3.5 cursor-pointer accent-[var(--accent-fill)]"
        />
        Invert — true when the project is NOT one of them
      </label>
    </div>
  );
}


/** The scripts plugin's two nodes (RADD-1269, reshaped by RADD-1272): the
 * Python lives ON THE NODE. Bespoke rather than generated from the schema
 * because the body wants a code editor, the ports / outputs are what the
 * canvas redraws handles and offers tokens from, and a Test box runs the body
 * as typed — a dry run never applies an action, so this is how a script is
 * tried before the automation is enabled. */
export function ScriptNodeFields({
  params,
  decide,
  onChange,
}: {
  params: Params;
  /** True for `script.decide` (ports), false for `script.run` (outputs). */
  decide: boolean;
  onChange: (params: Params) => void;
}) {
  const names = (params[decide ? "ports" : "outputs"] as string[]) ?? [];
  const [seed, setSeed] = useState("");
  const test = useMutation({
    mutationFn: () =>
      api.post<ScriptRunOutcome>(`${ApiPath.scripts}/run`, {
        body: String(params.body ?? ""),
        item_key: seed.trim(),
        params: Object.fromEntries(
          Object.entries(params).filter(([key]) => !["body", "timeout", "outputs", "ports", "arity", "act_as"].includes(key)),
        ),
        timeout: Math.min(Number(params.timeout) || 60, 120),
      }),
  });
  return (
    <div className="flex flex-col gap-2" data-script-node>
      <Labelled label="Script">
        <PythonEditor
          value={String(params.body ?? "")}
          onChange={(body) => onChange({ ...params, body })}
          minHeight={220}
        />
      </Labelled>
      <Labelled label={decide ? "Ports the script may name" : "Outputs the script returns"}>
        <TokenMultiSelect
          value={names}
          onChange={(next) => onChange({ ...params, [decide ? "ports" : "outputs"]: next })}
          options={[]}
          placeholder={decide ? "Add a port…" : "Add an output…"}
          ariaLabel={decide ? "Ports" : "Outputs"}
          allowCreate
        />
      </Labelled>
      <p className="text-xs text-fg-secondary">
        {decide
          ? "main(ctx) returns one of these names; anything else — or a failure — takes the unavailable port."
          : "main(ctx) returns a dict; each declared key becomes a token downstream, {{name.key}}."}
        {" "}It runs out of process, in the interpreter from Settings → Scripts, as this automation's identity.
      </p>
      <TextField
        label="Timeout (seconds)"
        type="number"
        min={1}
        max={600}
        value={String(params.timeout ?? 60)}
        onChange={(event) => onChange({ ...params, timeout: Number(event.target.value) || 60 })}
      />
      <div data-script-test className="flex flex-col gap-2 rounded border border-subtle bg-base/40 p-2">
        <div className="flex flex-wrap items-end gap-2">
          <TextField
            label="Test with item"
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
            placeholder="TD-42 (optional)"
            className="max-w-[160px]"
          />
          <Button type="button" size="sm" disabled={test.isPending || !String(params.body ?? "").trim()} onClick={() => test.mutate()}>
            <Play size={12} aria-hidden />
            {test.isPending ? "Running…" : "Test"}
          </Button>
          {test.isError && <span className="text-[11px] text-status-danger">{errorMessage(test.error)}</span>}
        </div>
        {test.data && <ScriptOutcomeView outcome={test.data} />}
      </div>
    </div>
  );
}

function ScriptOutcomeView({ outcome }: { outcome: ScriptRunOutcome }) {
  return (
    <div data-script-outcome={outcome.ok ? "ok" : "failed"} className="flex flex-col gap-1 text-[11px]">
      <div className="flex items-center gap-2">
        <span className={`rounded px-1.5 py-px text-[10px] uppercase tracking-wide ${outcome.ok ? "bg-emerald-500/15 text-emerald-300" : "bg-status-danger/15 text-status-danger"}`}>
          {outcome.ok ? "ok" : "failed"}
        </span>
        <span className="text-fg-muted">{outcome.duration_ms} ms</span>
        {outcome.error && <span className="text-status-danger">{outcome.error}</span>}
      </div>
      {outcome.ok && (
        <pre className="max-h-40 overflow-auto rounded border border-subtle bg-base p-2 text-fg">{JSON.stringify(outcome.result, null, 2)}</pre>
      )}
      {outcome.stderr && (
        <pre className="max-h-40 overflow-auto rounded border border-subtle bg-base p-2 text-fg-secondary">{outcome.stderr}</pre>
      )}
    </div>
  );
}
