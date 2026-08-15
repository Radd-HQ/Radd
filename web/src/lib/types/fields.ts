/** Fields registry + screens (field-layout config per project + issue type). */
import type { CustomFieldValue } from "./items";
// ---------------------------------------------------------------------------
// Fields registry
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Screens (field-layout config per project + issue type)
// ---------------------------------------------------------------------------

/** Where a field sits in the issue view. secondary = shown but collapsed by
 * default in the compact peek panel; hidden = never rendered. */
export const ScreenPlacement = {
  primary: "primary",
  secondary: "secondary",
  hidden: "hidden",
} as const;
export type ScreenPlacementValue = (typeof ScreenPlacement)[keyof typeof ScreenPlacement];

/** One resolved field placement (`GET /screens/effective`), in render order.
 * `field` is a builtin token (assignee/cycle/labels/sla/…) or `cf:<key>`. */
export interface EffectiveFieldRow {
  field: string;
  placement: ScreenPlacementValue;
  custom: boolean;
}

export interface EffectiveScreen {
  project_id: string;
  issue_type_id: string | null;
  source: "issue_type" | "project" | "default";
  fields: EffectiveFieldRow[];
}

/** One stored placement row for the screen editor (`GET/PUT /screens`). */
export interface ScreenFieldRow {
  field: string;
  placement: ScreenPlacementValue;
}

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

