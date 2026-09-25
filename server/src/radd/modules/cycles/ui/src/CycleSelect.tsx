import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown } from "lucide-react";
import { Button, Modal, ListSearchInput, DirectoryPager, QueryError, Spinner, Switch, usePagedDirectory } from "@radd/plugin-sdk";
import { cycleQuery, cyclesPageQuery } from "./directory-queries";
import { CYCLE_STATUS_META } from "./status";
import type { CycleSelectProps, CycleChoicesProps } from "./picker-contract";

/** A closed selector resolves only its current value. Opening it mounts a
 * bounded directory; every name search reaches the whole authorized catalog. */
export function CycleSelect({ value, onChange, valueBy = "id", selectedLabel, label, placeholder,
  emptyLabel = "No cycle", emptyValue = "", includeCompleted = true, datedOnly = false,
  disabled, title, error, hint, id, size = "md", className = "", projectId,
}: CycleSelectProps) {
  const generatedId = useId();
  const triggerId = id ?? generatedId;
  const [open, setOpen] = useState(false);
  const hasValue = Boolean(value) && value !== emptyValue;
  const definition = cycleQuery(value);
  const session = useId();
  const selected = useQuery({ ...definition, queryKey: [...definition.queryKey, session], gcTime: 0, staleTime: 0,
    enabled: hasValue && valueBy === "id" && !selectedLabel, retry: false });
  const selectedName = selectedLabel ?? (valueBy === "name" ? value : selected.data?.name);
  const emptyText = placeholder ?? (value === emptyValue ? emptyLabel : null) ?? "Choose a cycle…";
  const text = hasValue ? selectedName ?? (selected.isError ? "Unavailable cycle" : "Loading cycle…")
    : emptyText;
  return <div className={`flex min-w-0 flex-col gap-1.5 ${className}`}>
    {label && <label htmlFor={triggerId} className="text-xs font-medium text-fg-secondary">{label}</label>}
    <Button id={triggerId} variant="secondary" size={size} disabled={disabled} title={title}
      className={`w-full justify-between ${error ? "border-status-danger" : ""}`}
      aria-label={label ? undefined : placeholder ?? "Cycle"} aria-haspopup="dialog"
      aria-invalid={Boolean(error)} aria-describedby={error || hint ? `${triggerId}-hint` : undefined}
      onClick={() => setOpen(true)}>
      <span className="truncate">{text}</span><ChevronDown className="shrink-0" size={12} aria-hidden />
    </Button>
    {selected.isError && valueBy === "id" && !selectedLabel && <div><QueryError label="selected cycle" error={selected.error} /><Button variant="ghost" size="sm" onClick={() => void selected.refetch()}>Retry cycle name</Button></div>}
    {(error || hint) && <p id={`${triggerId}-hint`} className={`text-xs ${error ? "text-status-danger-ink" : "text-fg-muted"}`}>{error ?? hint}</p>}
    {open && <CycleChoices value={value} valueBy={valueBy} emptyLabel={emptyLabel}
      includeCompleted={includeCompleted} datedOnly={datedOnly} projectId={projectId} onClose={() => setOpen(false)}
      onSelect={cycle => { setOpen(false); onChange(cycle ? cycle[valueBy] : emptyValue, cycle); }} />}
  </div>;
}

export function CycleChoices({ value = "", valueBy = "id", emptyLabel = "No cycle", includeCompleted = true,
  datedOnly = false, onSelect, onClose, projectId,
}: CycleChoicesProps) {
  const [scope, setScope] = useState({ projectId, all: !projectId });
  if (scope.projectId !== projectId) setScope({ projectId, all: !projectId });
  const allCycles = scope.projectId === projectId ? scope.all : !projectId;
  const directory = usePagedDirectory(JSON.stringify([includeCompleted, datedOnly, projectId, allCycles]),
    (q, page) => cyclesPageQuery(q, page, undefined, includeCompleted, "", datedOnly, allCycles ? "" : projectId));
  return <Modal title="Choose a cycle" onClose={onClose}>
    {projectId && (
      <div className="mb-2 flex justify-end">
        <Switch label="All cycles" checked={allCycles} onChange={all => setScope({ projectId, all })} data-cycle-scope="all" />
      </div>
    )}
    <ListSearchInput value={directory.filter} onChange={directory.setFilter} placeholder="Search cycles by name…"
      total={directory.total} matched={directory.total} noun="cycles" />
    {emptyLabel && <Button variant="ghost" className="mt-2" onClick={() => onSelect(null)}>{emptyLabel}</Button>}
    <div className="mt-2 max-h-[45dvh] overflow-y-auto" aria-busy={directory.busy}>
      {directory.isError ? <div><QueryError label="cycles" error={directory.error} /><Button variant="secondary" onClick={() => void directory.refetch()}>Retry cycles</Button></div>
        : directory.isPending ? <Spinner />
        : !directory.rows.length ? <p className="py-4 text-sm text-fg-muted">No matching cycles.</p>
        : <ul>{directory.rows.map(cycle => <li key={cycle.id}>
          <Button variant="ghost" className="w-full justify-start" onClick={() => onSelect(cycle)}>
            <span aria-hidden className={`size-2 shrink-0 rounded-full ${(CYCLE_STATUS_META[cycle.status]?.dotClassName ?? "bg-fg-muted")}`} />
            <span className="truncate">{cycle.name}</span>
            <span className="ml-auto text-xs text-fg-muted">{(CYCLE_STATUS_META[cycle.status]?.label ?? cycle.status)}</span>
            {cycle[valueBy] === value && <Check size={12} aria-label="Selected" />}
          </Button>
        </li>)}</ul>}
    </div>
    <DirectoryPager {...directory} onPage={directory.setPage} label="cycle choices" />
  </Modal>;
}
