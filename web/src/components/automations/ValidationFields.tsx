/**
 * Builder forms for the spec-119 nodes: the validate TRIGGER and the check.
 *
 * Bespoke rather than `SchemaFields`-generated, because both are pickers over
 * live data. A generated form would show `targets` as a JSON array of
 * `{kind, id}` and ask an admin to paste UUIDs — which is not a form, it is a
 * text editor with a label on it.
 *
 * The target list is a ROW BUILDER for the same reason the server stores rows:
 * "this graph checks the incident form and the Bug type in two projects" is a
 * set, and any single-value control would silently keep only the last choice.
 */
import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import {
  formsQuery,
  issueTypesQuery,
  projectsQuery,
} from "../../lib/queries";
import {
  ValidationMode,
  ValidationTargetKind,
  type ValidationTarget,
  type ValidationTargetKindValue,
  type ValidationModeValue,
} from "../../lib/types";
import type { FieldDef } from "../../lib/types";
import { Button, ButtonVariant } from "../Button";
import { IconButton } from "../IconButton";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";

type Params = Record<string, unknown>;

/** Builtin field names a finding may address, with their human labels. Mirrors
 * the server's `BuiltinItemField`; a name here that the server does not know
 * would be refused on save, which is why the list is spelled out rather than
 * derived from whatever the SPA happens to render. */
const BUILTIN_FIELDS: [string, string][] = [
  ["title", "Title"],
  ["description", "Description"],
  ["state", "State"],
  ["priority", "Priority"],
  ["assignee", "Assignee"],
  ["reporter", "Reporter"],
  ["team", "Team"],
  ["labels", "Labels"],
  ["parent", "Parent"],
  ["start_date", "Start date"],
  ["target_date", "Target date"],
  ["cycle", "Cycle"],
  ["release", "Release"],
  ["flagged", "Flag"],
  ["estimate_points", "Points"],
];

const CUSTOM_FIELD_PREFIX = "cf.";

const TARGET_KIND_LABELS: [ValidationTargetKindValue, string][] = [
  [ValidationTargetKind.project, "Everything in a project"],
  [ValidationTargetKind.issueType, "One issue type"],
  [ValidationTargetKind.form, "One intake form"],
];

interface TargetOption {
  id: string;
  label: string;
}

/** Every pickable target, per kind, labelled so two projects' "Bug" types are
 * telling apart. Fetched HERE rather than added to `PickerData`, so the
 * per-project form and issue-type queries only run when someone is actually
 * editing a validate trigger. */
function useTargetOptions(): Record<ValidationTargetKindValue, TargetOption[]> {
  const projects = useQuery(projectsQuery());
  const rows = projects.data ?? [];
  const types = useQueries({ queries: rows.map((project) => issueTypesQuery(project.id)) });
  const forms = useQueries({ queries: rows.map((project) => formsQuery(project.id)) });

  return useMemo(() => {
    const project: TargetOption[] = rows.map((row) => ({
      id: row.id,
      label: `${row.key} · ${row.name}`,
    }));
    const issue_type: TargetOption[] = [];
    const form: TargetOption[] = [];
    rows.forEach((row, index) => {
      for (const issueType of types[index]?.data ?? []) {
        issue_type.push({ id: issueType.id, label: `${row.key} · ${issueType.name}` });
      }
      for (const intakeForm of forms[index]?.data ?? []) {
        form.push({ id: intakeForm.id, label: `${row.key} · ${intakeForm.name}` });
      }
    });
    return { project, issue_type, form };
    // The query arrays are new objects every render; their DATA is what matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, types.map((query) => query.data).join("|"), forms.map((query) => query.data).join("|")]);
}

export function ValidateTriggerFields({
  params,
  onChange,
}: {
  params: Params;
  onChange: (params: Params) => void;
}) {
  const options = useTargetOptions();
  const targets = (params.targets as ValidationTarget[] | undefined) ?? [];
  const mode = (params.mode as ValidationModeValue) ?? ValidationMode.advisory;

  const setTargets = (next: ValidationTarget[]) => onChange({ ...params, targets: next });
  const patch = (index: number, target: ValidationTarget) =>
    setTargets(targets.map((entry, at) => (at === index ? target : entry)));

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-fg-secondary">
        Runs when someone creates an issue here — <strong>before</strong> it exists. The checks it
        reaches decide whether the submission is accepted; nothing this graph contains is applied.
      </p>

      <div className="flex flex-col gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-fg-secondary">
          What it checks
        </span>
        {targets.length === 0 && (
          <p className="text-xs text-status-warning-ink">
            A validation trigger with no targets governs nothing and will never run.
          </p>
        )}
        {targets.map((target, index) => {
          const kind = target.kind ?? ValidationTargetKind.project;
          return (
            <div key={index} className="flex items-end gap-2">
              <SelectField
                label={index === 0 ? "Applies to" : ""}
                value={kind}
                // Switching the kind clears the id: an issue-type id is not a
                // form id, and keeping it would store a target that matches
                // nothing while looking configured.
                onChange={(event) =>
                  patch(index, {
                    kind: event.target.value as ValidationTargetKindValue,
                    id: "",
                  })
                }
                className="w-56"
              >
                {TARGET_KIND_LABELS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </SelectField>
              <SelectField
                label={index === 0 ? "Which" : ""}
                value={target.id ?? ""}
                onChange={(event) => patch(index, { kind, id: event.target.value })}
                className="flex-1"
              >
                <option value="">Choose…</option>
                {(options[kind] ?? []).map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </SelectField>
              <IconButton
                aria-label="Remove this target"
                onClick={() => setTargets(targets.filter((_, at) => at !== index))}
              >
                <Trash2 size={13} aria-hidden />
              </IconButton>
            </div>
          );
        })}
        <div>
          <Button
            variant={ButtonVariant.ghost}
            size="sm"
            onClick={() =>
              setTargets([...targets, { kind: ValidationTargetKind.project, id: "" }])
            }
          >
            <Plus size={12} aria-hidden /> Add a target
          </Button>
        </div>
      </div>

      <SelectField
        label="When a check fails"
        value={mode}
        onChange={(event) => onChange({ ...params, mode: event.target.value })}
        hint={
          mode === ValidationMode.required
            ? "Enforced for EVERY caller — the API and MCP included, not just the form."
            : "The findings are shown and the person may create it anyway."
        }
      >
        <option value={ValidationMode.advisory}>Show the findings — creating is still allowed</option>
        <option value={ValidationMode.required}>Refuse the creation</option>
      </SelectField>
    </div>
  );
}

export function ValidationFailFields({
  params,
  fields,
  onChange,
}: {
  params: Params;
  /** The custom-field registry, for the `cf.<key>` half of the picker. */
  fields: FieldDef[];
  onChange: (params: Params) => void;
}) {
  const target = String(params.field ?? "");
  return (
    <div className="flex flex-col gap-2">
      <TextField
        label="What to tell the person"
        value={String(params.message ?? "")}
        onChange={(event) => onChange({ ...params, message: event.target.value })}
        placeholder="Add the steps to reproduce, and what you expected to happen."
        hint="Reaching this node IS the check failing. Write it as advice, not as an error code."
      />
      <SelectField
        label="About which field"
        value={target}
        onChange={(event) => onChange({ ...params, field: event.target.value })}
        hint="Highlights that control on the form. Leave it general when the problem is the submission as a whole."
      >
        <option value="">The submission as a whole</option>
        <optgroup label="Built-in fields">
          {BUILTIN_FIELDS.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </optgroup>
        {fields.length > 0 && (
          <optgroup label="Custom fields">
            {fields.map((definition) => (
              <option
                key={definition.id}
                value={`${CUSTOM_FIELD_PREFIX}${definition.key}`}
              >
                {definition.name}
              </option>
            ))}
          </optgroup>
        )}
      </SelectField>
    </div>
  );
}
