/**
 * The search node's form (RADD-919) — the only node that PRODUCES items.
 *
 * Everything else on the canvas narrows what the trigger handed it, so the
 * hints here are doing real teaching work: someone who has only used filters
 * will read "SLQ" and expect it to apply to the triggering issue.
 */
import { SearchMode } from "../../lib/types";
import { SelectField } from "../SelectField";
import { TextField } from "../TextField";
import type { PickerData } from "./ActionsBuilder";

type Params = Record<string, unknown>;

interface SearchFieldsProps {
  params: Params;
  pickers: PickerData;
  onChange: (params: Params) => void;
}

export function SearchFields({ params, pickers, onChange }: SearchFieldsProps) {
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
      <SelectField
        label="Within"
        value={String(params.project ?? "")}
        onChange={(event) => set({ project: event.target.value })}
        hint="Scoping also decides which project's custom fields the query resolves against."
      >
        <option value="">Every project</option>
        {pickers.projectKeys.map((key) => (
          <option key={key} value={key}>
            {key}
          </option>
        ))}
      </SelectField>
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
