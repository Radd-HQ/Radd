import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { Button, QueryError } from "@radd/plugin-sdk";
import { projectByIdQuery, projectByKeyQuery } from "./directory-queries";
import { ProjectPicker } from "./ProjectPicker";
import type { ProjectSelectProps } from "./picker-contract";

/** Resolve the selected project directly; mount a bounded catalog only when opened. */
export function ProjectSelect({ value, onChange, label = "Project", emptyLabel = null,
  emptyValue = "", permission, disabled = false, hint, valueBy = "id",
}: ProjectSelectProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const current = value && value !== emptyValue ? value : "";
  const definition = valueBy === "key" ? projectByKeyQuery(current) : projectByIdQuery(current);
  const session = useId();
  const selected = useQuery({ ...definition, queryKey: [...definition.queryKey, session], gcTime: 0, staleTime: 0, retry: false });
  const hasValue = Boolean(value) && value !== emptyValue;
  const text = hasValue
    ? selected.data ? `${selected.data.key} · ${selected.data.name}`
      : selected.isPending ? "Loading project…" : "Unavailable project"
    : emptyLabel ?? "Choose a project…";
  return <div className="flex min-w-0 flex-col gap-1.5">
    <label htmlFor={id} className="text-xs font-medium text-fg-secondary">{label}</label>
    <Button id={id} variant="secondary" disabled={disabled} className="w-full justify-between"
      aria-haspopup="dialog" aria-describedby={hint ? `${id}-hint` : undefined} onClick={() => setOpen(true)}>
      <span className="truncate">{text}</span><ChevronDown size={12} className="shrink-0" aria-hidden />
    </Button>
    {selected.isError && <div><QueryError label="selected project" error={selected.error} /><Button variant="ghost" size="sm" onClick={() => void selected.refetch()}>Retry project name</Button></div>}
    {hint && <p id={`${id}-hint`} className="text-xs text-fg-muted">{hint}</p>}
    {open && <ProjectPicker title="Choose a project" permission={permission} selectedId={selected.data?.id}
      emptyLabel={emptyLabel ?? undefined} onClear={() => { setOpen(false); onChange(emptyValue, null); }}
      onSelect={project => { setOpen(false); onChange(project[valueBy], project); }} onClose={() => setOpen(false)} />}
  </div>;
}
