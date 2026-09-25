import { OptionChoices, Button, QueryError } from "@radd/plugin-sdk";
import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { teamReferencesQuery } from "./references";
import type { TeamSelectProps, TeamChoicesProps } from "./relationship-contract";

/** ID-valued team relationships resolve the saved value without a catalog. */
export function TeamSelect({ value, onChange, label, selectedLabel, placeholder, emptyLabel = "None", disabled, title, error, size = "md" }: TeamSelectProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const definition = teamReferencesQuery(value ? [value] : []);
  const selected = useQuery({ ...definition, queryKey: [...definition.queryKey, id],
    gcTime: 0, staleTime: 0, retry: false, enabled: Boolean(value) && !selectedLabel });
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

export function TeamChoices({ selected = [], emptyLabel, onSelect, onClose, footer }: TeamChoicesProps) {
  return <OptionChoices resource="teams/directory" title="Choose a team" selectedValues={selected}
    presets={emptyLabel ? [{ value: "", label: emptyLabel, hint: "" }] : []}
    onSelect={row => onSelect(row.value)} onClose={onClose} footer={footer} />;
}
