import { useId } from "react";
import {
  FieldType,
  type CustomFieldValue,
  type CustomFields,
  type FieldDef,
} from "../../lib/types";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import { TokenMultiSelect } from "../TokenMultiSelect";

interface CustomFieldsFormProps {
  fields: FieldDef[];
  values: CustomFields;
  /** Per-field-key validation errors (from the registry's 422 payload). */
  errors: Record<string, string>;
  onChange: (key: string, value: CustomFieldValue) => void;
  /** Per-field write lock (spec 92): a restricted field renders disabled + dimmed, with a reason. */
  lockFor?: (key: string) => { locked: boolean; reason: string };
}

/**
 * Form generated from the fields registry (`GET /fields`) —
 * one control per definition, rendered by field type (spec 04 §Phase 2).
 * Values map 1:1 to the item's `custom_fields`; null clears a value.
 */
export function CustomFieldsForm({
  fields,
  values,
  errors,
  onChange,
  lockFor,
}: CustomFieldsFormProps) {
  if (fields.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      {fields.map((field) => {
        const lock = lockFor?.(field.key) ?? { locked: false, reason: "" };
        return (
          <fieldset
            key={field.id}
            disabled={lock.locked}
            title={lock.locked ? lock.reason : undefined}
            className="min-w-0 disabled:opacity-70"
          >
            <CustomFieldControl
              field={field}
              value={values[field.key] ?? null}
              error={errors[field.key]}
              onChange={(value) => onChange(field.key, value)}
            />
          </fieldset>
        );
      })}
    </div>
  );
}

interface ControlProps {
  field: FieldDef;
  value: CustomFieldValue;
  error?: string;
  onChange: (value: CustomFieldValue) => void;
}

function fieldLabel(field: FieldDef): string {
  return field.required ? `${field.name} *` : field.name;
}

/**
 * A single registry-field control rendered by field type — the reusable unit
 * behind `CustomFieldsForm`. Exported so the intake-form submit page (spec 20)
 * and the automations `set_custom_field` action can render one field with their
 * own label/required overrides (pass a synthesized `FieldDef`).
 */
export function CustomFieldControl({ field, value, error, onChange }: ControlProps) {
  switch (field.type) {
    case FieldType.select:
      return (
        <SelectField
          label={fieldLabel(field)}
          value={typeof value === "string" ? value : ""}
          error={error}
          onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        >
          <option value="">—</option>
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </SelectField>
      );

    case FieldType.multi_select:
      // One compact single-row token editor for both display modes (spec 94 UX pass): the field's
      // `display` no longer forks the widget — the token select scrolls rather than growing tall.
      return <MultiSelectField field={field} value={value} error={error} onChange={onChange} />;

    case FieldType.boolean:
      return <BooleanToggle field={field} value={value} error={error} onChange={onChange} />;

    case FieldType.number:
      return (
        <TextField
          label={fieldLabel(field)}
          type="number"
          value={typeof value === "number" ? String(value) : ""}
          error={error}
          onChange={(event) =>
            onChange(event.target.value === "" ? null : Number(event.target.value))
          }
        />
      );

    case FieldType.duration:
      return (
        <TextField
          label={fieldLabel(field)}
          type="number"
          min={0}
          step={1}
          hint="Minutes"
          value={typeof value === "number" ? String(value) : ""}
          error={error}
          onChange={(event) =>
            onChange(event.target.value === "" ? null : Number(event.target.value))
          }
        />
      );

    case FieldType.date:
      return (
        <TextField
          label={fieldLabel(field)}
          type="date"
          value={typeof value === "string" ? value : ""}
          error={error}
          onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        />
      );

    case FieldType.url:
    case FieldType.user:
    case FieldType.text:
      return (
        <TextField
          label={fieldLabel(field)}
          type={field.type === FieldType.url ? "url" : "text"}
          hint={field.type === FieldType.user ? "User id" : undefined}
          value={typeof value === "string" ? value : ""}
          error={error}
          onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        />
      );
  }
}

/** A registry multi_select field: one compact single-row token editor over the field's options —
 *  type to filter + pick, × / Backspace to remove. Replaces the old chips + dropdown variants. */
function MultiSelectField({ field, value, error, onChange }: ControlProps) {
  const selected = Array.isArray(value) ? value : [];
  const options = (field.options ?? []).map((option) => ({ value: option, label: option }));
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-fg-secondary">{fieldLabel(field)}</span>
      <TokenMultiSelect
        value={selected}
        onChange={(next) => onChange(next.length > 0 ? next : null)}
        options={options}
        invalid={Boolean(error)}
        placeholder="Select…"
        ariaLabel={field.name}
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}

function BooleanToggle({ field, value, error, onChange }: ControlProps) {
  const id = useId();
  const checked = value === true;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="text-xs font-medium text-fg-secondary">
          {fieldLabel(field)}
        </label>
        <button
          id={id}
          type="button"
          role="switch"
          aria-checked={checked}
          onClick={() => onChange(!checked)}
          className={
            "relative h-5 w-9 rounded-full transition-colors cursor-pointer " +
            "focus-visible:outline-2 focus-visible:outline-focus " +
            (checked ? "bg-accent" : "bg-strong")
          }
        >
          <span
            className={
              "absolute top-0.5 size-4 rounded-full bg-white transition-transform " +
              (checked ? "translate-x-4" : "translate-x-0.5")
            }
          />
        </button>
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}
