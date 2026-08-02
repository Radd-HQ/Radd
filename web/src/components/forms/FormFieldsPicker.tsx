import { ChevronDown, ChevronUp, Trash2 } from "lucide-react";
import { FIELD_TYPE_LABELS } from "../../lib/meta";
import type { FieldDef, FormField } from "../../lib/types";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";

interface FormFieldsPickerProps {
  /** Registry fields in the form's project scope (global + project-scoped). */
  available: FieldDef[];
  value: FormField[];
  onChange: (fields: FormField[]) => void;
}

/**
 * Ordered picker of registry fields a form exposes (spec 20): each chosen field
 * gets a label override, help text, and a required toggle. Fields resolve by key
 * (`field_key`) against the project's registry scope.
 */
export function FormFieldsPicker({ available, value, onChange }: FormFieldsPickerProps) {
  const chosen = new Set(value.map((field) => field.field_key));
  const addable = available.filter((definition) => !chosen.has(definition.key));
  const defByKey = (key: string) => available.find((definition) => definition.key === key);

  const update = (index: number, next: FormField) =>
    onChange(value.map((field, i) => (i === index ? next : field)));
  const remove = (index: number) => onChange(value.filter((_, i) => i !== index));
  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= value.length) return;
    const next = [...value];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };
  const add = (key: string) => {
    if (!key || chosen.has(key)) return;
    onChange([...value, { field_key: key, label_override: null, help: null, required: false }]);
  };

  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium text-fg-secondary">Fields</span>

      {value.length === 0 && (
        <p className="rounded-md border border-dashed border-subtle px-3 py-4 text-center text-xs text-fg-faint">
          No fields yet — the form will just take a title. Add registry fields below.
        </p>
      )}

      <ul className="flex flex-col gap-2">
        {value.map((field, index) => {
          const definition = defByKey(field.field_key);
          return (
            <li
              key={field.field_key}
              className="flex items-start gap-2 rounded-md border border-subtle bg-surface/40 p-2.5"
            >
              <div className="flex flex-col gap-0.5 pt-1">
                <button
                  type="button"
                  onClick={() => move(index, -1)}
                  disabled={index === 0}
                  aria-label="Move field up"
                  className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg disabled:opacity-30 cursor-pointer disabled:cursor-default"
                >
                  <ChevronUp size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => move(index, 1)}
                  disabled={index === value.length - 1}
                  aria-label="Move field down"
                  className="rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg disabled:opacity-30 cursor-pointer disabled:cursor-default"
                >
                  <ChevronDown size={13} />
                </button>
              </div>
              <div className="flex min-w-0 flex-1 flex-col gap-2.5">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-elevated px-1 font-mono text-[11px] text-fg">
                    {field.field_key}
                  </span>
                  {definition && (
                    <span className="text-[11px] text-fg-muted">
                      {definition.name} · {FIELD_TYPE_LABELS[definition.type]}
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-2.5">
                  <TextField
                    label="Label override"
                    value={field.label_override ?? ""}
                    placeholder={definition?.name ?? "Default label"}
                    maxLength={200}
                    onChange={(event) =>
                      update(index, { ...field, label_override: event.target.value || null })
                    }
                  />
                  <TextField
                    label="Help text"
                    value={field.help ?? ""}
                    placeholder="Shown under the field"
                    maxLength={1000}
                    onChange={(event) => update(index, { ...field, help: event.target.value || null })}
                  />
                </div>
                <label className="flex w-fit cursor-pointer items-center gap-2 text-xs text-fg">
                  <input
                    type="checkbox"
                    checked={field.required}
                    onChange={(event) => update(index, { ...field, required: event.target.checked })}
                    className="size-3.5 accent-accent"
                  />
                  Required on this form
                </label>
              </div>
              <button
                type="button"
                onClick={() => remove(index)}
                aria-label={`Remove field ${field.field_key}`}
                className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer"
              >
                <Trash2 size={14} />
              </button>
            </li>
          );
        })}
      </ul>

      <div className="w-64">
        <SelectField
          label="Add a field"
          value=""
          onChange={(event) => add(event.target.value)}
          hint={addable.length === 0 ? "All registry fields in scope are added" : undefined}
          disabled={addable.length === 0}
        >
          <option value="">Select a registry field…</option>
          {addable.map((definition) => (
            <option key={definition.id} value={definition.key}>
              {definition.name} ({FIELD_TYPE_LABELS[definition.type]})
            </option>
          ))}
        </SelectField>
      </div>
    </div>
  );
}
