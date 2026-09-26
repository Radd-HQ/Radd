import type { FieldDef } from "@radd-plugin-ui/fields/types";
import { OptionSelect } from "@radd/plugin-sdk";
import { OptionResource } from "./options";
import { ProjectSelect } from "./controls";
/** Forms for the validate trigger and verdicts: pickers over live data, and targets as a ROW builder
 * (a set — a single control would keep only the last choice). */
import { Plus, Trash2 } from "lucide-react";
import {
  ValidationTargetKind,
  type ValidationTarget,
  type ValidationTargetKindValue,
} from "./types";

import { Button, ButtonVariant } from "@radd/plugin-sdk";
import { IconButton } from "@radd/plugin-sdk";
import { SelectField } from "@radd/plugin-sdk";
import { TextField } from "@radd/plugin-sdk";

type Params = Record<string, unknown>;

/** Mirrors the server's `BuiltinItemField`; an unknown name is refused on save. */
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

export function ValidateTriggerFields({
  params,
  onChange,
}: {
  params: Params;
  onChange: (params: Params) => void;
}) {
  const targets = (params.targets as ValidationTarget[] | undefined) ?? [];

  const setTargets = (next: ValidationTarget[]) => onChange({ ...params, targets: next });
  const patch = (index: number, target: ValidationTarget) =>
    setTargets(targets.map((entry, at) => (at === index ? target : entry)));

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-fg-secondary">
        Runs when someone creates an issue here — <strong>before</strong> it exists. Nothing it
        reaches is applied: a <strong>Block submission</strong> node refuses the submission, a{" "}
        <strong>Warn submitter</strong> node shows a problem they can submit past. The chip on this
        trigger says which it can do.
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
            <div key={index} className="flex flex-wrap items-end gap-2">
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
              {kind === ValidationTargetKind.project
                ? <ProjectSelect label="Which" value={target.id ?? ""} onChange={id => patch(index, { kind, id })} />
                : <OptionSelect label="Which" resource={kind === ValidationTargetKind.form ? OptionResource.form : OptionResource.issueType}
                    value={target.id ?? ""} onChange={id => patch(index, { kind, id })} />}
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

    </div>
  );
}

/** "Block submission" / "Warn submitter" (RADD-1329): say a fixed message, or
 * RELAY what an upstream check found in its own words. */
export function VerdictFields({
  params,
  fields,
  blocks,
  checks,
  onChange,
}: {
  params: Params;
  /** The custom-field registry, for the `cf.<key>` half of the picker. */
  fields: FieldDef[];
  /** Block submission (true) or Warn submitter (false). */
  blocks: boolean;
  /** Upstream nodes that publish findings, which this node may relay. */
  checks: { id: string; label: string }[];
  onChange: (params: Params) => void;
}) {
  const relay = String(params.relay ?? "");
  const relaying = Boolean(relay) || (params.message === undefined && checks.length > 0 && params.relay !== undefined);
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-fg-secondary">
        {blocks
          ? "Reaching this node refuses the submission. The person sees why, and cannot create it until it is fixed."
          : "Reaching this node shows the person a problem. They can fix it, or submit again to create it anyway."}
      </p>
      <SelectField
        label="Tell them"
        value={relaying ? "relay" : "message"}
        onChange={(event) =>
          onChange(
            event.target.value === "relay"
              ? { relay: checks[0]?.id ?? "" }
              : { message: "", field: "" },
          )
        }
      >
        <option value="message">A message you write</option>
        <option value="relay" disabled={checks.length === 0}>
          What a check found{checks.length === 0 ? " (no check upstream)" : ""}
        </option>
      </SelectField>
      {relaying ? (
        <SelectField
          label="Which check"
          value={relay}
          onChange={(event) => onChange({ relay: event.target.value })}
          hint={
            blocks
              ? "Its findings, in its own words. A problem the check graded minor still only advises."
              : "Its findings, in its own words — all of them advice."
          }
        >
          {checks.map((check) => (
            <option key={check.id} value={check.id}>
              {check.label}
            </option>
          ))}
        </SelectField>
      ) : (
        <VerdictMessage params={params} fields={fields} onChange={onChange} />
      )}
    </div>
  );
}

function VerdictMessage({
  params,
  fields,
  onChange,
}: {
  params: Params;
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
        hint="Write it as advice. {{item.title}} always means the original submitted draft, even after a search. Other field tokens are not allowed here."
      />
      <SelectField
        label="About which field"
        value={target}
        onChange={(event) => onChange({ ...params, field: event.target.value })}
        hint="Highlights that control on the form. Leave it general when the problem is the submission as a whole."
      >
        <option value="">The submission as a whole</option>
        {target.startsWith(CUSTOM_FIELD_PREFIX) && !fields.some(field => `${CUSTOM_FIELD_PREFIX}${field.key}` === target)
          && <option value={target}>{target} (unavailable field)</option>}
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
