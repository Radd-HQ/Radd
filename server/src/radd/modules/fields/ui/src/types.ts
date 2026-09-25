/** Public Fields values: null clears; all other values retain their type. */
export type CustomFieldValue = string | number | boolean | string[] | null;
export type CustomFields = Record<string, CustomFieldValue>;

export const FieldType = {
  text: "text",
  number: "number",
  boolean: "boolean",
  date: "date",
  select: "select",
  multi_select: "multi_select",
  user: "user",
  url: "url",
  duration: "duration",
} as const;
export type FieldTypeValue = (typeof FieldType)[keyof typeof FieldType];


export const FieldDisplay = { chips: "chips", dropdown: "dropdown" } as const;
export type FieldDisplayValue = (typeof FieldDisplay)[keyof typeof FieldDisplay];

export interface FieldDef {
  id: string;
  /** Empty = global (every project); otherwise the projects this field is scoped to. */
  project_ids: string[];
  key: string;
  name: string;
  type: FieldTypeValue;
  required: boolean;
  options: string[] | null;
  indexed: boolean;
  ai_visible: boolean;
  source: string;
  /** Spec 52: render hint (select/multi_select) — "chips" | "dropdown" | null(default). */
  display: FieldDisplayValue | null;
  /** Seeded onto new items when the create payload omits this key; null = no default. */
  default_value: CustomFieldValue;
  /** Spec 92: the field carries access grants (managed via /grants), so some actors
   * can't see or write it. Grant details are fetched separately by the GrantsEditor. */
  restricted: boolean;
  created_at: string;
}

/** POST /fields. */
export interface FieldDefCreate {
  /** Empty/omitted = global; otherwise scope the field to these projects. */
  project_ids?: string[];
  key: string;
  name: string;
  type: FieldTypeValue;
  required?: boolean;
  options?: string[] | null;
  default_value?: CustomFieldValue;
}

