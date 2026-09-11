import { useId, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { teamReferencesQuery } from "../../lib/queries/users";
import { OptionResource, OPTIONS_PAGE_SIZE, optionsPageQuery } from "../../lib/queries/options";
import { useDirectory } from "../../lib/useDirectory";
import { Button } from "../Button";
import { DirectoryPager } from "../DirectoryPager";
import { Modal } from "../Modal";
import { QueryError } from "../QueryError";
import { Spinner } from "../Spinner";
import { TextField } from "../TextField";

/** ID-valued team relationships resolve the saved value without a catalog. */
export function TeamSelect({ value, onChange, label, selectedLabel, placeholder, emptyLabel = "None", disabled, title, error, size = "md" }: {
  value: string; onChange: (id: string) => void; label?: string; selectedLabel?: string;
  placeholder?: string; emptyLabel?: string; disabled?: boolean; title?: string; error?: string; size?: "sm" | "md";
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const selected = useQuery({ ...teamReferencesQuery(value ? [value] : []), enabled: Boolean(value) && !selectedLabel });
  const text = value ? selectedLabel ?? selected.data?.find(row => row.id === value)?.name ?? (selected.isPending ? "Loading team…" : "Unavailable team") : placeholder ?? emptyLabel;
  return <div className="flex min-w-0 flex-col gap-1.5">
    {label && <label htmlFor={id} className="text-xs font-medium text-fg-secondary">{label}</label>}
    <Button id={id} variant="secondary" size={size} disabled={disabled} title={title} className="w-full justify-between"
      aria-label={label ? undefined : placeholder ?? "Team"} aria-haspopup="dialog" aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} onClick={() => setOpen(true)}>
      <span className="truncate">{text}</span><ChevronDown size={12} className="shrink-0" aria-hidden />
    </Button>
    {selected.isError && !selectedLabel && <div><QueryError label="selected team" error={selected.error} /><Button size="sm" variant="ghost" onClick={() => void selected.refetch()}>Retry team name</Button></div>}
    {error && <p id={`${id}-error`} role="alert" className="text-xs text-status-danger-ink">{error}</p>}
    {open && <TeamChoices selected={value ? [value] : []} emptyLabel={emptyLabel} onClose={() => setOpen(false)} onSelect={id => { onChange(id); setOpen(false); }} />}
  </div>;
}

export function TeamChoices({ selected = [], emptyLabel, onSelect, onClose, footer }: {
  selected?: string[]; emptyLabel?: string; onSelect: (id: string) => void; onClose: () => void; footer?: ReactNode;
}) {
  const directory = useDirectory("team-references", OPTIONS_PAGE_SIZE, (q, page) => optionsPageQuery(OptionResource.teamReference, q, page));
  return <Modal title="Choose a team" onClose={onClose}>
    <TextField type="search" label="Find teams" value={directory.filter} onChange={event => directory.setFilter(event.target.value)} />
    {emptyLabel && <Button variant="ghost" className="mt-2" onClick={() => onSelect("")}>{emptyLabel}</Button>}
    <div aria-busy={directory.busy} className="mt-2 max-h-[45dvh] overflow-y-auto">
      {directory.isPending ? <Spinner label="Loading teams…" /> : directory.isError ? <div><QueryError label="team choices" error={directory.error} /><Button variant="secondary" onClick={() => void directory.refetch()}>Retry teams</Button></div>
        : !directory.rows.length ? <p className="text-sm text-fg-muted">No matching teams available.</p>
        : <ul aria-label="Team choices">{directory.rows.map(row => <li key={row.value}><Button variant="ghost" disabled={selected.includes(row.value)} className="w-full justify-start" onClick={() => onSelect(row.value)}><span className="truncate">{row.label}</span></Button></li>)}</ul>}
    </div>
    <DirectoryPager {...directory} onPage={directory.setPage} label="team choices" />
    {footer}
  </Modal>;
}
