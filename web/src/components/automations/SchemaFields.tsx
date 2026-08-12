/**
 * A form generated from a contributed node's JSON Schema (RADD-923).
 *
 * `AutomationNodeSpec.params_schema` has always promised that "the SPA generates
 * a form from it when the plugin ships no component of its own" — the same deal
 * `PageExtensionSpec` offers. Nothing generated it. A contributed node without a
 * hardcoded editor (only `ai.classify` had one) rendered as an empty inspector:
 * the node existed, could be dropped on the canvas, and could not be configured.
 *
 * Deliberately small — string, enum, number, boolean, and ONE nested shape: an
 * object whose properties are all booleans, rendered as a titled checkbox group
 * (RADD-1064). That shape earns its exception because it is what "which parts of
 * this do you want?" looks like in JSON Schema, and the generic renderer used to
 * meet it with a free-text input: `ai.validate`'s `include` invited a string
 * where the node reads a mapping, which is a node that silently checks nothing.
 * Anything richer than that is still a sign the plugin should ship its own
 * component through the slot registry.
 */
import { defaultsFromSchema } from "../../lib/automation-nodes";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";

type Params = Record<string, unknown>;

interface SchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  enum?: unknown[];
  default?: unknown;
  maxLength?: number;
  properties?: Record<string, SchemaProperty>;
}

/** An object property this form can render: every sub-property is a boolean.
 * Asked rather than assumed — an object of mixed types falls through to the
 * text input, which is honest about not understanding it. */
function isBooleanGroup(property: SchemaProperty): boolean {
  const sub = Object.values(property.properties ?? {});
  return property.type === "object" && sub.length > 0 && sub.every((p) => p.type === "boolean");
}

/** A checkbox group for one such property.
 *
 * A stored value that is NOT an object is read as the schema's defaults
 * (RADD-1064). Repairing it here rather than refusing is what makes the form
 * self-healing for the nodes saved while this rendered as a text box: the
 * checkboxes show what the node will actually do, and the first click writes the
 * shape the server and the node both expect. */
function BooleanGroup({
  property,
  value,
  onChange,
}: {
  property: SchemaProperty;
  value: unknown;
  onChange: (value: Record<string, boolean>) => void;
}) {
  const defaults = defaultsFromSchema(property as Record<string, unknown>) as Record<string, boolean>;
  const stored = (value && typeof value === "object" && !Array.isArray(value) ? value : {}) as Record<
    string,
    unknown
  >;
  const current = { ...defaults, ...stored };
  return (
    <div className="flex flex-col gap-1" data-schema-group={property.title || ""}>
      <span className="text-[11px] font-medium uppercase tracking-wide text-fg-secondary">
        {property.title}
      </span>
      <div className="flex flex-col gap-1">
        {Object.entries(property.properties ?? {}).map(([key, sub]) => (
          <label key={key} className="flex cursor-pointer items-start gap-2 text-[13px] text-fg">
            <input
              type="checkbox"
              data-schema-check={key}
              checked={Boolean(current[key])}
              onChange={(event) =>
                onChange({ ...(current as Record<string, boolean>), [key]: event.target.checked })
              }
              className="mt-0.5 size-3.5 cursor-pointer accent-[var(--accent-fill)]"
            />
            <span>{sub.title || key}</span>
          </label>
        ))}
      </div>
      {property.description && <p className="text-xs text-fg-secondary">{property.description}</p>}
    </div>
  );
}

interface SchemaFieldsProps {
  schema: Record<string, unknown>;
  params: Params;
  onChange: (params: Params) => void;
}

export function SchemaFields({ schema, params, onChange }: SchemaFieldsProps) {
  const properties = (schema.properties ?? {}) as Record<string, SchemaProperty>;
  const required = new Set((schema.required as string[]) ?? []);
  const entries = Object.entries(properties);
  if (entries.length === 0) return null;

  const set = (key: string, value: unknown) => onChange({ ...params, [key]: value });

  return (
    <div className="flex flex-col gap-2" data-schema-fields>
      {entries.map(([key, property]) => {
        const label = property.title || key;
        const value = params[key];

        if (property.enum) {
          return (
            <SelectField
              key={key}
              label={label}
              value={String(value ?? "")}
              hint={property.description}
              onChange={(event) => set(key, event.target.value)}
            >
              {/* No blank option when the field is required — offering a value
                  the server refuses is the affordance-then-error pattern. */}
              {!required.has(key) && <option value="">—</option>}
              {property.enum.map((option) => (
                <option key={String(option)} value={String(option)}>
                  {String(option)}
                </option>
              ))}
            </SelectField>
          );
        }

        if (isBooleanGroup(property)) {
          return (
            <BooleanGroup
              key={key}
              property={property}
              value={value}
              onChange={(next) => set(key, next)}
            />
          );
        }

        if (property.type === "boolean") {
          return (
            <label key={key} className="flex cursor-pointer items-center gap-2 text-[13px] text-fg">
              <input
                type="checkbox"
                checked={Boolean(value)}
                onChange={(event) => set(key, event.target.checked)}
                className="size-3.5 cursor-pointer accent-[var(--accent-fill)]"
              />
              {label}
            </label>
          );
        }

        const numeric = property.type === "number" || property.type === "integer";
        return (
          <TextField
            key={key}
            label={label}
            value={value === undefined || value === null ? "" : String(value)}
            hint={property.description}
            type={numeric ? "number" : undefined}
            required={required.has(key)}
            onChange={(event) =>
              set(key, numeric ? Number(event.target.value) : event.target.value)
            }
          />
        );
      })}
    </div>
  );
}
