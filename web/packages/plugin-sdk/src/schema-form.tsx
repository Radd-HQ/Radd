/** Small domain-independent schema form. Richer structures belong to a contributed editor. */
import { TextField } from "./primitives";
import { SelectField } from "./host";
import type { SchemaFormProps } from "./host-registry";
import { defaultsFromSchema, type SchemaProperty } from "./schema-defaults";

const displayValue = (value: unknown) => typeof value === "string" ? value || "(empty text)" : JSON.stringify(value);

function BooleanGroup({ property, value, onChange }: { property: SchemaProperty; value: unknown; onChange: (value: Record<string, unknown>) => void }) {
  const defaults = defaultsFromSchema(property as Record<string, unknown>);
  const stored = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const normalized = Object.fromEntries(Object.keys(property.properties ?? {}).map(key => [key,
    typeof stored[key] === "boolean" ? stored[key] : defaults[key] === true,
  ]));
  return <fieldset className="flex flex-col gap-1" data-schema-group={property.title || ""}>
    <legend className="text-[11px] font-medium uppercase tracking-wide text-fg-secondary">{property.title}</legend>
    {Object.entries(property.properties ?? {}).map(([key, sub]) => <label key={key} className="flex cursor-pointer items-start gap-2 text-[13px] text-fg">
      <input type="checkbox" data-schema-check={key} checked={normalized[key]} onChange={event => onChange({ ...stored, ...normalized, [key]: event.target.checked })} className="mt-0.5 size-3.5 cursor-pointer accent-[var(--accent-fill)]" />
      <span>{sub.title || key}</span>
    </label>)}
    {property.description && <p className="text-xs text-fg-secondary">{property.description}</p>}
  </fieldset>;
}

export function SchemaForm({ schema, params, onChange }: SchemaFormProps) {
  const properties = (schema.properties ?? {}) as Record<string, SchemaProperty>;
  const required = new Set((schema.required as string[]) ?? []);
  const set = (key: string, value: unknown) => {
    const next = { ...params };
    if (value === undefined) delete next[key];
    else Object.defineProperty(next, key, { value, enumerable: true, configurable: true, writable: true });
    onChange(next);
  };
  return <div className="flex flex-col gap-2" data-schema-fields>
    {Object.entries(properties).map(([key, property]) => {
      const label = property.title || key, value = params[key];
      if (property.enum) {
        const index = property.enum.findIndex(option => JSON.stringify(option) === JSON.stringify(value));
        const unknown = value !== undefined && index < 0;
        return <SelectField key={key} label={label} value={unknown ? "saved" : index < 0 ? "" : String(index)} hint={property.description}
          onChange={event => {
            const chosen = event.target.value;
            if (chosen !== "saved") set(key, chosen === "" ? undefined : structuredClone(property.enum![Number(chosen)]));
          }}>
          {!required.has(key) && <option value="">—</option>}
          {unknown && <option value="saved">Saved value: {displayValue(value)}</option>}
          {property.enum.map((option, at) => <option key={at} value={String(at)}>{displayValue(option)}</option>)}
        </SelectField>;
      }
      const sub = Object.values(property.properties ?? {});
      if (property.type === "object" && sub.length && sub.every(p => p.type === "boolean")) {
        return <BooleanGroup key={key} property={{ ...property, title: label }} value={value} onChange={next => set(key, next)} />;
      }
      if (property.type === "boolean") return <label key={key} className="flex cursor-pointer items-center gap-2 text-[13px] text-fg">
        <input type="checkbox" checked={value === true} onChange={event => set(key, event.target.checked)} className="size-3.5 cursor-pointer accent-[var(--accent-fill)]" />{label}
      </label>;
      const numeric = property.type === "number" || property.type === "integer";
      if ((property.type && !["string", "number", "integer"].includes(property.type)) || (value !== null && typeof value === "object")) {
        return <div key={key} data-schema-unsupported={key} className="text-xs text-fg-secondary">
          <p>{label}: this value needs a custom editor.</p>
          {value !== undefined && <pre className="whitespace-pre-wrap break-words">{JSON.stringify(value, null, 2)}</pre>}
        </div>;
      }
      return <TextField key={key} label={label} value={value == null ? "" : String(value)} hint={property.description}
        type={numeric ? "number" : undefined} required={required.has(key)} maxLength={property.maxLength}
        min={property.minimum} max={property.maximum} step={property.type === "integer" ? 1 : "any"}
        onChange={event => set(key, numeric ? event.target.value === "" ? undefined : Number(event.target.value) : event.target.value)} />;
    })}
  </div>;
}
