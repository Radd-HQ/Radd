/** The search node's form — the only node that PRODUCES items, hence the teaching hints. */
import { ProjectSelect } from "./controls";
import { SearchMode } from "./types";
import { SelectField } from "@radd/plugin-sdk";
import { TextField } from "@radd/plugin-sdk";

type Params = Record<string, unknown>;

interface SearchFieldsProps {
  params: Params;
  onChange: (params: Params) => void;
}

export function SearchFields({ params, onChange }: SearchFieldsProps) {
  const set = (patch: Params) => onChange({ ...params, ...patch });

  return (
    <div className="flex flex-col gap-2">
      <TextField
        label="Find issues where"
        value={String(params.slq ?? "")}
        onChange={(event) => set({ slq: event.target.value })}
        placeholder="state = Todo AND updated < today-14d"
        hint="SLQ, run when this node is reached. Empty finds nothing — not everything."
      />
      <ProjectSelect label="Within" valueBy="key" value={String(params.project ?? "")}
        onChange={project => set({ project })} emptyLabel="Every project"
        hint="Scoping also decides which project's custom fields the query resolves against." />
      <SelectField
        label="What reaches this node"
        value={String(params.mode ?? SearchMode.replace)}
        onChange={(event) => set({ mode: event.target.value })}
      >
        <option value={SearchMode.replace}>Is replaced by what I find</option>
        <option value={SearchMode.add}>Is kept, and what I find is added</option>
      </SelectField>
    </div>
  );
}
