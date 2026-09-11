import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown } from "lucide-react";
import { cycleQuery } from "../../lib/queries/cycles";
import { useCycleDirectory } from "../../lib/useCycleDirectory";
import { CYCLE_STATUS_META } from "../../lib/meta";
import type { Cycle } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { ListSearchInput } from "../ListSearchInput";
import { DirectoryPager } from "../DirectoryPager";
import { QueryError } from "../QueryError";
import { Spinner } from "../Spinner";

interface Props {
  value: string;
  onChange: (value: string, cycle: Cycle | null) => void;
  /** Automation and form defaults persist names; issue fields persist IDs. */
  valueBy?: "id" | "name";
  selectedLabel?: string;
  label?: string;
  placeholder?: string;
  emptyLabel?: string | null;
  emptyValue?: string;
  includeCompleted?: boolean;
  datedOnly?: boolean;
  disabled?: boolean;
  title?: string;
  error?: string;
  hint?: string;
  id?: string;
  size?: "sm" | "md";
  className?: string;
}

/** A closed selector resolves only its current value. Opening it mounts a
 * bounded directory; every name search reaches the whole authorized catalog. */
export function CycleSelect({ value, onChange, valueBy = "id", selectedLabel, label, placeholder,
  emptyLabel = "No cycle", emptyValue = "", includeCompleted = true, datedOnly = false,
  disabled, title, error, hint, id, size = "md", className = "",
}: Props) {
  const generatedId = useId();
  const triggerId = id ?? generatedId;
  const [open, setOpen] = useState(false);
  const hasValue = Boolean(value) && value !== emptyValue;
  const selected = useQuery({ ...cycleQuery(value), enabled: hasValue && valueBy === "id" && !selectedLabel, retry: false });
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
    {(error || hint) && <p id={`${triggerId}-hint`} className={`text-xs ${error ? "text-status-danger-ink" : "text-fg-muted"}`}>{error ?? hint}</p>}
    {open && <CycleChoices value={value} valueBy={valueBy} emptyLabel={emptyLabel}
      includeCompleted={includeCompleted} datedOnly={datedOnly} onClose={() => setOpen(false)}
      onSelect={cycle => { setOpen(false); onChange(cycle ? cycle[valueBy] : emptyValue, cycle); }} />}
  </div>;
}

export function CycleChoices({ value = "", valueBy = "id", emptyLabel = "No cycle", includeCompleted = true,
  datedOnly = false, onSelect, onClose,
}: {
  value?: string; valueBy?: "id" | "name"; emptyLabel?: string | null;
  includeCompleted?: boolean; datedOnly?: boolean;
  onSelect: (cycle: Cycle | null) => void; onClose: () => void;
}) {
  const directory = useCycleDirectory({ includeCompleted, datedOnly });
  return <Modal title="Choose a cycle" onClose={onClose}>
    <ListSearchInput value={directory.filter} onChange={directory.setFilter} placeholder="Search cycles by name…"
      total={directory.total} matched={directory.total} noun="cycles" />
    {emptyLabel && <Button variant="ghost" className="mt-2" onClick={() => onSelect(null)}>{emptyLabel}</Button>}
    <div className="mt-2 max-h-[45dvh] overflow-y-auto" aria-busy={directory.busy}>
      {directory.isError ? <QueryError label="cycles" error={directory.error} />
        : directory.isPending ? <Spinner label="Loading cycles…" />
        : !directory.rows.length ? <p className="py-4 text-sm text-fg-muted">No matching cycles.</p>
        : <ul>{directory.rows.map(cycle => <li key={cycle.id}>
          <Button variant="ghost" className="w-full justify-start" onClick={() => onSelect(cycle)}>
            <span aria-hidden className={`size-2 shrink-0 rounded-full ${CYCLE_STATUS_META[cycle.status].dotClassName}`} />
            <span className="truncate">{cycle.name}</span>
            <span className="ml-auto text-xs text-fg-muted">{CYCLE_STATUS_META[cycle.status].label}</span>
            {cycle[valueBy] === value && <Check size={12} aria-label="Selected" />}
          </Button>
        </li>)}</ul>}
    </div>
    <DirectoryPager {...directory} onPage={directory.setPage} label="cycle choices" />
  </Modal>;
}
