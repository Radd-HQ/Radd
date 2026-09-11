import { useQueries } from "@tanstack/react-query";
import { X } from "lucide-react";
import { cycleQuery } from "../../lib/queries/cycles";
import { CycleSelect } from "./CycleSelect";
import { IconButton } from "../IconButton";

/** Conditions retain selected IDs/names; adding a value searches the catalog.
 * Only legacy selections without saved display names need direct lookups. */
export function CycleConditionValues({ values, display, single, disabled, onChange }: {
  values: string[]; display: string[]; single: boolean; disabled: boolean;
  onChange: (values: string[], display: string[]) => void;
}) {
  const current = useQueries({ queries: values.map((id, index) => ({
    ...cycleQuery(id), enabled: !display[index], retry: false,
  })) });
  const names = values.map((_id, index) => display[index] || current[index].data?.name || "Unavailable cycle");
  return <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
    {values.map((value, index) => <span key={value} className="inline-flex max-w-full items-center rounded border border-subtle px-1 text-xs text-fg">
      <span className="truncate">{names[index]}</span>
      {!disabled && <IconButton aria-label={`Remove ${names[index]}`} onClick={() =>
        onChange(values.filter(id => id !== value), names.filter((_name, at) => at !== index))}><X size={12} /></IconButton>}
    </span>)}
    <CycleSelect value="" placeholder={single && values.length ? "Replace cycle…" : "Add cycle…"}
      emptyLabel="Clear values" disabled={disabled} size="sm" onChange={(id, cycle) => {
        if (!cycle) onChange([], []);
        else if (single) onChange([id], [cycle.name]);
        else if (!values.includes(id)) onChange([...values, id], [...names, cycle.name]);
      }} />
  </div>;
}
