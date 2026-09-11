import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { projectByIdQuery, projectByKeyQuery } from "../../lib/queries/projects";
import type { PermissionValue, Project } from "../../lib/types";
import { Button } from "../Button";
import { ProjectPicker } from "./ProjectPicker";

/** Resolve the selected project directly; mount a bounded catalog only when opened. */
export function ProjectSelect({ value, onChange, label = "Project", emptyLabel = null,
  emptyValue = "", permission, disabled = false, hint, valueBy = "id",
}: {
  value: string; onChange: (id: string, project: Project | null) => void;
  label?: string; emptyLabel?: string | null; emptyValue?: string;
  valueBy?: "id" | "key";
  permission?: PermissionValue; disabled?: boolean; hint?: string;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const current = value && value !== emptyValue ? value : "";
  const byId = useQuery(projectByIdQuery(valueBy === "id" ? current : ""));
  const byKey = useQuery(projectByKeyQuery(valueBy === "key" ? current : ""));
  const selected = valueBy === "key" ? byKey : byId;
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
    {hint && <p id={`${id}-hint`} className="text-xs text-fg-muted">{hint}</p>}
    {open && <ProjectPicker title="Choose a project" permission={permission} selectedId={selected.data?.id}
      emptyLabel={emptyLabel ?? undefined} onClear={() => { setOpen(false); onChange(emptyValue, null); }}
      onSelect={project => { setOpen(false); onChange(project[valueBy], project); }} onClose={() => setOpen(false)} />}
  </div>;
}
