import { useState } from "react";
import { SelectField } from "../../SelectField";

/** Bounded editor for the existing value_map contract; unmapped values pass through. */
export function ValueMappings({ values, targets, mapping, onChange }: {
  values: string[]; targets: string[]; mapping: Record<string, string>;
  onChange: (mapping: Record<string, string>) => void;
}) {
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(20);
  const [custom, setCustom] = useState<string | null>(null);
  const unique = [...new Set(values)];
  const choices = [...new Set(targets)];
  const filtered = unique.filter(value => `${value} ${mapping[value] ?? ""}`.toLowerCase().includes(search.toLowerCase()));
  const set = (source: string, value?: string) => {
    const next = { ...mapping };
    if (value === undefined) delete next[source]; else next[source] = value;
    onChange(next);
  };
  if (!unique.length) return null;
  return <details className="mt-2 rounded border border-subtle p-2 text-xs">
    <summary className="cursor-pointer text-fg-secondary">Translate values · {unique.length} source values · {Object.keys(mapping).length} changed</summary>
    <p className="my-2 text-fg-muted">Choose a RADD value for each Jira value. Unchanged values keep their original text. A new option must also be allowed by the target field.</p>
    {unique.length > 20 && <input aria-label="Find source value" value={search} onChange={e => { setSearch(e.target.value); setLimit(20); }} placeholder="Find source value…" className="mb-2 rounded border border-strong bg-surface p-2"/>}
    {filtered.slice(0, limit).map(source => <div key={source} className="mb-2 flex flex-wrap items-end gap-3">
      <span className="w-48 break-words py-2" title={source}>Jira: {source}</span>
      <SelectField label="RADD value" ariaLabel={`${source}: RADD value`} value={custom === source ? "custom" : mapping[source] === undefined ? "keep" : choices.includes(mapping[source]) ? `value:${mapping[source]}` : "custom"}
        onChange={e => { const v = e.target.value; setCustom(v === "custom" ? source : null); if (v === "keep") set(source); else if (v.startsWith("value:")) set(source, v.slice(6)); }}>
        <option value="keep">Keep “{source}”</option>
        {choices.map(target => <option key={target} value={`value:${target}`}>{target}</option>)}
        <option value="custom">Enter another value…</option>
      </SelectField>
      {(custom === source || (mapping[source] !== undefined && !choices.includes(mapping[source]))) && <label className="flex flex-col gap-1">New target value<input aria-label={`${source}: new target value`} value={mapping[source] ?? ""} onChange={e => set(source, e.target.value)} className="h-8 rounded border border-strong bg-surface px-2 text-heading"/></label>}
    </div>)}
    {filtered.length > limit && <button type="button" className="underline" onClick={() => setLimit(n => n + 20)}>Show 20 more values ({filtered.length - limit} remaining)</button>}
  </details>;
}
