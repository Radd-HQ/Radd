import type { PageExtensionSpec } from "../../lib/types";

/**
 * Reading a `PageExtensionSpec.params_schema` as a form (RADD-747).
 *
 * The information was already on the wire — types, enums, defaults, `required`,
 * descriptions — and `GET /pages/extensions` already served it. What was missing
 * was anything that read it, so people found out that a callout accepts `title`
 * and `text` by guessing.
 *
 * Kept apart from the dialog on purpose: this is the only place that knows what
 * a JSON Schema property means, so a new widget is one entry here rather than a
 * branch in a component.
 */

export const FieldKind = {
  text: "text",
  markdown: "markdown",
  boolean: "boolean",
  integer: "integer",
  enum: "enum",
} as const;
export type FieldKindValue = (typeof FieldKind)[keyof typeof FieldKind];

export interface SchemaField {
  key: string;
  label: string;
  kind: FieldKindValue;
  description?: string;
  required: boolean;
  default?: unknown;
  options?: string[];
  minimum?: number;
  maximum?: number;
}

interface RawProperty {
  type?: string;
  format?: string;
  enum?: unknown[];
  default?: unknown;
  description?: string;
  minimum?: number;
  maximum?: number;
}

/** `title_prompt` → `Title prompt`. The schema rarely carries a title. */
const labelFor = (key: string) =>
  key.replace(/[_-]+/g, " ").replace(/^./, (c) => c.toUpperCase());

/**
 * The fields a spec's schema describes, in declaration order.
 *
 * A property whose type nothing here understands is DROPPED rather than
 * guessed at — the dialog keeps its raw-JSON view for exactly that, and a
 * silently mis-rendered control would be worse than an honest gap.
 */
export function fieldsOf(spec: PageExtensionSpec | undefined): SchemaField[] {
  const properties = (spec?.params_schema?.properties ?? {}) as Record<string, RawProperty>;
  const required = new Set(spec?.params_schema?.required ?? []);
  const fields: SchemaField[] = [];
  for (const [key, property] of Object.entries(properties)) {
    const kind = kindOf(property);
    if (!kind) continue;
    fields.push({
      key,
      label: labelFor(key),
      kind,
      description: property.description,
      required: required.has(key),
      default: property.default,
      options: kind === FieldKind.enum ? property.enum?.map(String) : undefined,
      minimum: property.minimum,
      maximum: property.maximum,
    });
  }
  return fields;
}

function kindOf(property: RawProperty): FieldKindValue | null {
  if (Array.isArray(property.enum) && property.enum.length) return FieldKind.enum;
  if (property.type === "boolean") return FieldKind.boolean;
  if (property.type === "integer" || property.type === "number") return FieldKind.integer;
  if (property.type === "string") {
    return property.format === "markdown" ? FieldKind.markdown : FieldKind.text;
  }
  return null;
}

/**
 * Fold the form's values back into the block's parameters.
 *
 * Two rules, both about not damaging what the author wrote:
 *
 *  - **Unknown keys survive.** A parameter this build's schema does not describe
 *    — because a plugin was upgraded, downgraded or disabled — is carried
 *    through untouched. Dropping it would silently rewrite someone's page.
 *  - **A value equal to the default is omitted** unless it was already written
 *    out. The block stays as short as the author left it instead of accreting
 *    `"depth": 3` on every save, and an explicit value someone chose to write is
 *    still respected.
 */
export function mergeParams(
  existing: Record<string, unknown>,
  fields: SchemaField[],
  values: Record<string, unknown>,
): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...existing };
  for (const field of fields) {
    const value = values[field.key];
    const wasPresent = Object.prototype.hasOwnProperty.call(existing, field.key);
    const isEmpty =
      value === undefined || value === null || (typeof value === "string" && value === "");
    const isDefault = field.default !== undefined && value === field.default;

    if (isEmpty && !field.required) {
      delete merged[field.key];
    } else if (isDefault && !wasPresent) {
      delete merged[field.key];
    } else {
      merged[field.key] = value;
    }
  }
  return merged;
}

/** The value a field starts on: what the block says, else the schema's default. */
export function initialValues(
  fields: SchemaField[],
  params: Record<string, unknown>,
): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const field of fields) {
    const stored = params[field.key];
    values[field.key] = stored !== undefined ? stored : (field.default ?? blankFor(field.kind));
  }
  return values;
}

const blankFor = (kind: FieldKindValue) =>
  kind === FieldKind.boolean ? false : kind === FieldKind.integer ? undefined : "";

/** Everything the form cannot show, so the dialog can say so rather than hide it. */
export function unknownKeys(
  params: Record<string, unknown>,
  fields: SchemaField[],
): string[] {
  const known = new Set(fields.map((field) => field.key));
  return Object.keys(params).filter((key) => !known.has(key));
}
