/**
 * A form generated from a contributed node's JSON Schema (RADD-923).
 *
 * `AutomationNodeSpec.params_schema` has always promised that "the SPA generates
 * a form from it when the plugin ships no component of its own" — the same deal
 * `PageExtensionSpec` offers. Nothing generated it. A contributed node without a
 * hardcoded editor (only `ai.classify` had one) rendered as an empty inspector:
 * the node existed, could be dropped on the canvas, and could not be configured.
 *
 * Deliberately small — string, enum, number, boolean. Anything richer is a sign
 * the plugin should ship its own component through the slot registry, and a
 * half-clever generic renderer for nested objects would produce a form nobody
 * can use out of a schema nobody can read.
 */
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
