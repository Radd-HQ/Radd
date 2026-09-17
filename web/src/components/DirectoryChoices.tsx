import { useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown } from "lucide-react";
import { type DirectoryOption, type OptionResourceValue, OptionResource, OPTIONS_PAGE_SIZE, optionsPageQuery, optionByValueQuery } from "../lib/queries/options";
import { useDirectory } from "../lib/useDirectory";
import { Button } from "./Button";
import { Modal } from "./Modal";
import { DirectoryPager } from "./DirectoryPager";
import { QueryError } from "./QueryError";
import { Spinner } from "./Spinner";
import { TextField } from "./TextField";
import { TokenMultiSelect } from "./TokenMultiSelect";

const nouns = { [OptionResource.state]: "state names", [OptionResource.release]: "release versions",
  [OptionResource.issueType]: "issue types", [OptionResource.form]: "intake forms", [OptionResource.user]: "people", [OptionResource.team]: "team names", [OptionResource.role]: "roles", [OptionResource.space]: "wiki spaces", [OptionResource.person]: "people", [OptionResource.teamReference]: "teams", [OptionResource.group]: "directory groups", [OptionResource.assignableRole]: "roles" };

/** Complete directory via search/pages, with only one window mounted. */
export function Choices({ resource, selected = "", onSelect, onClose, presets = [], canBrowse = true, selectedValues = [], scope = {} }: {
  scope?: Record<string, string>; resource: OptionResourceValue; selected?: string; presets?: DirectoryOption[]; canBrowse?: boolean; selectedValues?: string[];
  onSelect: (option: DirectoryOption) => void; onClose: () => void;
}) {
  const directory = useDirectory(`${resource}:${JSON.stringify(scope)}`, OPTIONS_PAGE_SIZE, (q, page) => ({ ...optionsPageQuery(resource, q, page, scope), enabled: canBrowse }));
  return <Modal title={`Choose ${nouns[resource]}`} onClose={onClose}>
    {canBrowse && <TextField type="search" label={`Find ${nouns[resource]}`} value={directory.filter}
      onChange={event => directory.setFilter(event.target.value)} placeholder="Search…" />}
    {presets.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{presets.map(row => <Button key={row.value} variant="secondary" onClick={() => onSelect(row)}>{row.label}</Button>)}</div>}
    {canBrowse && <><div aria-busy={directory.busy} className="mt-3 max-h-[45dvh] overflow-y-auto">
      {directory.isPending ? <Spinner label="Loading choices…" />
        : directory.isError ? <div className="space-y-2"><QueryError label={nouns[resource]} error={directory.error} />
          <Button variant="secondary" onClick={() => void directory.refetch()}>Retry choices</Button></div>
        : !directory.rows.length ? <p className="py-3 text-sm text-fg-muted">No matching choices.</p>
        : <ul>{directory.rows.map(row => <li key={row.value}>
          <Button variant="ghost" disabled={selectedValues.includes(row.value)} className={`w-full justify-start ${resource === OptionResource.user ? "h-auto min-h-11 py-2" : ""}`} onClick={() => onSelect(row)}>
            {resource === OptionResource.user ? <span className="min-w-0 text-left" title={`${row.label} · ${row.hint}`}>
              <span className="block truncate">{row.label}</span>
              <span className="block truncate text-xs text-fg-muted">{row.hint}</span>
            </span> : <>
              {row.hint && <span className="max-w-[45%] shrink-0 truncate font-mono text-xs">{row.hint}</span>}
              <span className="truncate">{row.label}</span>
            </>}
            {(row.value === selected || selectedValues.includes(row.value)) && <Check size={12} className="ml-auto shrink-0" aria-label="Selected" />}
          </Button>
        </li>)}</ul>}
    </div>
    <DirectoryPager {...directory} onPage={directory.setPage} label={nouns[resource]} /></>}
  </Modal>;
}

/** Names remain editable: template tokens, future vocabulary and clear values round-trip. */
export function OptionTextField({ resource, label, value, onChange, hint, placeholder, canBrowse = true, suggestions = [] }: {
  resource: OptionResourceValue; label: string; value: string; onChange: (value: string) => void;
  hint?: string; placeholder?: string; canBrowse?: boolean; suggestions?: string[];
}) {
  const [open, setOpen] = useState(false);
  const suggestionsId = useId();
  return <div className="flex min-w-0 flex-col gap-1">
    {suggestions.length > 0 && <datalist id={suggestionsId}>{suggestions.map(value => <option key={value} value={value} />)}</datalist>}
    <TextField list={suggestions.length ? suggestionsId : undefined} label={label} value={value} onChange={event => onChange(event.target.value)} hint={hint} placeholder={placeholder} />
    {canBrowse && <Button size="sm" variant="ghost" className="w-fit" onClick={() => setOpen(true)}>Browse {nouns[resource]}</Button>}
    {open && <Choices resource={resource} selected={value} onClose={() => setOpen(false)}
      onSelect={row => { setOpen(false); onChange(row.value); }} />}
  </div>;
}

/** References store IDs/names/emails; resolve one saved value without a catalog. */
export function OptionSelect({ resource, label, value, onChange, presets = [], canBrowse = true }: {
  resource: OptionResourceValue; label: string; value: string; onChange: (value: string) => void;
  presets?: DirectoryOption[]; canBrowse?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const preset = presets.find(row => row.value === value);
  const selected = useQuery({ ...optionByValueQuery(resource, value), enabled: Boolean(value) && !preset && canBrowse });
  const choice = preset ?? selected.data?.[0];
  const missing = resource === OptionResource.user || resource === OptionResource.team ? value : "Unavailable choice";
  const text = choice ? (resource === OptionResource.user ? [choice.label, choice.hint] : [choice.hint, choice.label]).filter(Boolean).join(" · ")
    : value ? !canBrowse ? missing : selected.isPending ? "Loading choice…" : missing : "Choose…";
  return <div className="flex min-w-0 flex-1 flex-col gap-1.5">
    <label htmlFor={id} className="text-xs font-medium text-fg-secondary">{label}</label>
    <Button id={id} variant="secondary" className="w-full justify-between" aria-haspopup="dialog" onClick={() => setOpen(true)}>
      <span className="truncate">{text}</span><ChevronDown size={12} className="shrink-0" aria-hidden />
    </Button>
    {open && <Choices resource={resource} selected={value} presets={presets} canBrowse={canBrowse} onClose={() => setOpen(false)}
      onSelect={row => { setOpen(false); onChange(row.value); }} />}
  </div>;
}

/** Multi-value conditions retain arbitrary old values while adding searchable names. */
export function OptionNameValues({ resource, label, value, onChange, canBrowse = true }: {
  resource: OptionResourceValue; label: string; value: string[]; onChange: (values: string[]) => void; canBrowse?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return <div className="flex min-w-0 flex-col gap-1">
    <TokenMultiSelect value={value} onChange={onChange} options={value.map(value => ({ value, label: value }))}
      ariaLabel={label} placeholder="Add a value…" allowCreate />
    {canBrowse && <Button variant="ghost" size="sm" className="w-fit" onClick={() => setOpen(true)}>Browse {nouns[resource]}</Button>}
    {open && <Choices resource={resource} onClose={() => setOpen(false)}
      onSelect={row => { setOpen(false); if (!value.includes(row.value)) onChange([...value, row.value]); }} />}
  </div>;
}
