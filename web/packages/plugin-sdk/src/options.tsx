/** Searchable option controls. Providers own transport, nouns, scope and row meaning. */
import { useEffect, useId, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Slot } from "./slots";
import { Button, Modal, Spinner, TextField } from "./primitives";
import { DirectoryPager, QueryError, TokenList } from "./host";
import type { Paged } from "./api";
import type { PluginContribution } from "./plugin";

export interface DirectoryOption { value: string; label: string; hint: string }
type Scope = Record<string, string>;
interface Common { resource: string; canBrowse?: boolean; scope?: Scope }
export interface OptionChoicesProps extends Common {
  selected?: string; presets?: DirectoryOption[]; selectedValues?: string[];
  title?: string; footer?: ReactNode;
  onSelect: (option: DirectoryOption) => void; onClose: () => void;
}
export interface OptionSelectProps extends Common {
  label: string; value: string; onChange: (value: string) => void; presets?: DirectoryOption[];
}
export interface OptionTextFieldProps extends OptionSelectProps {
  hint?: string; placeholder?: string; suggestions?: string[];
}
export interface OptionNameValuesProps extends Common {
  label: string; value: string[]; onChange: (values: string[]) => void;
}
type Request = ({ kind: "choices" } & OptionChoicesProps) | ({ kind: "select" } & OptionSelectProps)
  | ({ kind: "text" } & OptionTextFieldProps) | ({ kind: "names" } & OptionNameValuesProps);
export interface OptionSource {
  resource: string;
  noun: string;
  /** Owner-defined presentation, with no resource-specific conditions in the control. */
  hintAfter?: boolean;
  stacked?: boolean;
  meta?: Record<string, unknown>;
  fetch: (args: { q: string; limit: number; offset: number; scope: Scope; signal: AbortSignal }) => Promise<Paged<DirectoryOption>>;
  resolve: (args: { value: string; scope: Scope; signal: AbortSignal }) => Promise<DirectoryOption[]>;
}
export const OPTION_CONTROL_SLOT = "directory.options";

/** Register a feature's option source through normal plugin lifecycle ownership. */
export function optionContribution(source: OptionSource): PluginContribution {
  return { id: `options:${source.resource}`, slot: OPTION_CONTROL_SLOT, match: source.resource, toggleable: false,
    render: props => <OptionControl {...(props as unknown as Request)} source={source} /> };
}
function ContributedOption(props: Request) {
  const fallback = <OptionControl {...props} />;
  return <Slot id={OPTION_CONTROL_SLOT} match={props.resource} {...props} fallback={fallback} errorFallback={fallback} />;
}
export function OptionChoices(props: OptionChoicesProps) { return <ContributedOption kind="choices" {...props} />; }
export function OptionSelect(props: OptionSelectProps) { return <ContributedOption kind="select" {...props} />; }
export function OptionTextField(props: OptionTextFieldProps) { return <ContributedOption kind="text" {...props} />; }
export function OptionNameValues(props: OptionNameValuesProps) { return <ContributedOption kind="names" {...props} />; }

function OptionControl(props: Request & { source?: OptionSource }) {
  if (props.kind === "choices") return <Choices {...props} />;
  if (props.kind === "select") return <SelectControl {...props} />;
  return <EditableControl {...props} />;
}
function choiceText(row: DirectoryOption, source?: OptionSource) {
  return (source?.hintAfter ? [row.label, row.hint] : [row.hint, row.label]).filter(Boolean).join(" · ");
}
function SelectControl({ source, label, value, onChange, presets = [], canBrowse = true, scope = {}, resource }: OptionSelectProps & { source?: OptionSource }) {
  const id = useId(), session = useId();
  const [open, setOpen] = useState(false);
  const preset = presets.find(row => row.value === value);
  const active = Boolean(source && canBrowse && value && !preset);
  const selected = useQuery({ queryKey: ["directory-options", resource, "value", value, scope, session],
    queryFn: ({ signal }) => source!.resolve({ value, scope, signal }), meta: source?.meta,
    enabled: active, gcTime: 0, staleTime: 0, retry: false });
  const choice = preset ?? (active ? selected.data?.[0] : undefined);
  const text = choice ? choiceText(choice, source) : value
    ? active && selected.isPending ? "Loading choice…" : `${value} (unavailable)` : "Choose…";
  return <div className="flex min-w-0 flex-1 flex-col gap-1.5">
    <label htmlFor={id} className="text-xs font-medium text-fg-secondary">{label}</label>
    <Button id={id} variant="secondary" className="w-full justify-between" aria-haspopup="dialog"
      disabled={!(source && canBrowse) && !presets.length} onClick={() => setOpen(true)}><span className="truncate">{text}</span><span aria-hidden>⌄</span></Button>
    {selected.isError && active && <div className="text-xs"><QueryError label="choice" error={selected.error} /><Button variant="ghost" size="sm" onClick={() => void selected.refetch()}>Retry choice</Button></div>}
    {open && <Choices resource={resource} source={source} scope={scope} selected={value} presets={presets} canBrowse={canBrowse}
      onClose={() => setOpen(false)} onSelect={row => { setOpen(false); onChange(row.value); }} />}
  </div>;
}
function EditableControl(props: (({ kind: "text" } & OptionTextFieldProps) | ({ kind: "names" } & OptionNameValuesProps)) & { source?: OptionSource }) {
  const [open, setOpen] = useState(false);
  const suggestionsId = useId();
  const noun = props.source?.noun ?? "choices";
  return <div className="flex min-w-0 flex-col gap-1">
    {props.kind === "text" ? <>
      {!!props.suggestions?.length && <datalist id={suggestionsId}>{props.suggestions.map(value => <option key={value} value={value} />)}</datalist>}
      <TextField list={props.suggestions?.length ? suggestionsId : undefined} label={props.label} value={props.value}
        onChange={event => props.onChange(event.target.value)} hint={props.hint} placeholder={props.placeholder} />
    </> : <TokenList value={props.value} onChange={props.onChange} ariaLabel={props.label} placeholder="Add a value…" />}
    {props.canBrowse !== false && <Button variant="ghost" size="sm" className="w-fit" disabled={!props.source}
      title={!props.source ? "This directory is unavailable" : undefined} onClick={() => setOpen(true)}>Browse {noun}</Button>}
    {open && <Choices resource={props.resource} source={props.source} scope={props.scope} canBrowse={props.canBrowse} onClose={() => setOpen(false)}
      selected={props.kind === "text" ? props.value : undefined} selectedValues={props.kind === "names" ? props.value : undefined}
      onSelect={row => { setOpen(false); if (props.kind === "text") props.onChange(row.value);
        else if (!props.value.includes(row.value)) props.onChange([...props.value, row.value]); }} />}
  </div>;
}
function Choices({ source, resource, selected = "", selectedValues = [], presets = [], canBrowse = true, scope = {}, onSelect, onClose, title, footer }: OptionChoicesProps & { source?: OptionSource }) {
  const session = useId();
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { const timer = setTimeout(() => setQ(filter.trim()), 150); return () => clearTimeout(timer); }, [filter]);
  const [position, setPosition] = useState({ q, scope: JSON.stringify(scope), page: 0 });
  const scopeKey = JSON.stringify(scope);
  if (position.q !== q || position.scope !== scopeKey) setPosition({ q, scope: scopeKey, page: 0 });
  const page = position.q === q && position.scope === scopeKey ? position.page : 0;
  const pageSize = 50, active = Boolean(source && canBrowse), noun = source?.noun ?? "choices";
  const result = useQuery({ queryKey: ["directory-options", resource, { q, page }, scope, session], meta: source?.meta,
    queryFn: ({ signal }) => source!.fetch({ q, limit: pageSize, offset: page * pageSize, scope, signal }),
    enabled: active, gcTime: 0, staleTime: 0, retry: false });
  const busy = result.isFetching || q !== filter.trim();
  const rows = active ? result.data?.rows ?? [] : [];
  return <Modal title={title ?? `Choose ${noun}`} onClose={onClose}>
    {active && <TextField type="search" label={`Find ${noun}`} value={filter} onChange={event => setFilter(event.target.value)} placeholder="Search…" />}
    {presets.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{presets.map(row => <Button key={row.value} variant="secondary" disabled={selectedValues.includes(row.value)} onClick={() => onSelect(row)}>{row.label}</Button>)}</div>}
    {!source && <p className="py-3 text-sm text-fg-muted">This directory is unavailable. Saved values are preserved.</p>}
    {active && <><div aria-busy={busy} className="mt-3 max-h-[45dvh] overflow-y-auto">
      {result.isPending ? <Spinner /> : result.isError ? <div className="space-y-2"><QueryError label={noun} error={result.error} /><Button variant="secondary" onClick={() => void result.refetch()}>Retry choices</Button></div>
        : !rows.length ? <p className="py-3 text-sm text-fg-muted">No matching choices.</p>
        : <ul>{rows.map(row => <li key={row.value}><Button variant="ghost" disabled={selectedValues.includes(row.value)}
          className={`w-full justify-start ${source?.stacked ? "h-auto min-h-11 py-2" : ""}`} onClick={() => onSelect(row)}>
          {source?.stacked ? <span className="min-w-0 text-left" title={choiceText(row, source)}><span className="block truncate">{row.label}</span><span className="block truncate text-xs text-fg-muted">{row.hint}</span></span>
            : <span className="truncate">{choiceText(row, source)}</span>}
          {(row.value === selected || selectedValues.includes(row.value)) && <span className="ml-auto shrink-0" aria-label="Selected">✓</span>}
        </Button></li>)}</ul>}
    </div><DirectoryPager page={page} pageSize={pageSize} total={result.data?.total ?? rows.length} busy={busy}
      onPage={next => setPosition({ q, scope: scopeKey, page: next })} label={noun} /></>}
    {footer}
  </Modal>;
}
