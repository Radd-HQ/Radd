import type { CustomFieldValue, CustomFields, FieldDef } from "./types";
export const FIELD_CONTROL_SLOT = "fields.control";
export const FIELDS_FORM_SLOT = "fields.form";

export interface CustomFieldsFormProps {
  fields: FieldDef[];
  values: CustomFields;
  /** Per-field-key validation errors (from the registry's 422 payload). */
  errors: Record<string, string>;
  onChange: (key: string, value: CustomFieldValue) => void;
  /** Per-field write lock (spec 92): a restricted field renders disabled + dimmed, with a reason. */
  lockFor?: (key: string) => { locked: boolean; reason: string };
}

export interface ControlProps {
  disabled?: boolean;
  field: FieldDef;
  value: CustomFieldValue;
  error?: string;
  onChange: (value: CustomFieldValue) => void;
}

