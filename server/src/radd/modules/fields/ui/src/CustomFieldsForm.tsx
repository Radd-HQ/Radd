import { useId } from "react";
import { SelectField, TextField, TokenMultiSelect, ErrorText } from "@radd/plugin-sdk";
import { FieldType, type FieldDef } from "./types";
import type { CustomFieldsFormProps, ControlProps } from "./control-contract";

/** One control per registry field (`GET /fields`); null clears a value. */
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
              disabled={lock.locked}
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

function fieldLabel(field: FieldDef): string {
  return field.required ? `${field.name} *` : field.name;
}

/** One field's control — also rendered alone by intake forms and automations with a synthesized FieldDef. */
export function CustomFieldControl({ field, value, error, onChange, disabled }: ControlProps) {
  switch (field.type) {
    case FieldType.select:
      return (
        <SelectField
          disabled={disabled}
          label={fieldLabel(field)}
          value={typeof value === "string" ? value : ""}
          error={error}
          onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        >
          <option value="">—</option>
          {typeof value === "string" && value !== "" && !(field.options ?? []).includes(value)
            && <option value={value}>{value} (unavailable option)</option>}
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </SelectField>
      );

    case FieldType.multi_select:
      return <MultiSelectField field={field} value={value} error={error} onChange={onChange} disabled={disabled} />;

    case FieldType.boolean:
      return <BooleanToggle field={field} value={value} error={error} onChange={onChange} disabled={disabled} />;

    case FieldType.number:
      return (
        <TextField
          disabled={disabled}
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
          disabled={disabled}
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
          disabled={disabled}
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
          disabled={disabled}
          label={fieldLabel(field)}
          type={field.type === FieldType.url ? "url" : "text"}
          hint={field.type === FieldType.user ? "User id" : undefined}
          value={typeof value === "string" ? value : ""}
          error={error}
          onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        />
      );
    default:
      return <TextField label={fieldLabel(field)} disabled
        value={value == null ? "" : typeof value === "string" ? value : JSON.stringify(value)}
        hint="This field type is unavailable. The saved value is preserved." error={error} />;
  }
}

/** multi_select: one-row token editor. */
function MultiSelectField({ field, value, error, onChange, disabled }: ControlProps) {
  const selected = Array.isArray(value) ? value : [];
  const options = (field.options ?? []).map((option) => ({ value: option, label: option }));
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-fg-secondary">{fieldLabel(field)}</span>
      <TokenMultiSelect
        disabled={disabled}
        value={selected}
        onChange={(next) => onChange(next.length > 0 ? next : null)}
        options={options}
        invalid={Boolean(error)}
        placeholder="Select…"
        ariaLabel={field.name}
      />
      {error && <ErrorText error={error} />}
    </div>
  );
}

function BooleanToggle({ field, value, error, onChange, disabled }: ControlProps) {
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
          disabled={disabled}
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
              "absolute left-0.5 top-0.5 size-4 rounded-full bg-white transition-transform " +
              (checked ? "translate-x-4" : "translate-x-0")
            }
          />
        </button>
      </div>
      {error && <ErrorText error={error} />}
    </div>
  );
}
