import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Slot } from "./slots";
import { Button, Modal, Spinner } from "./primitives";
import { QueryError, DirectoryPager, ListSearchInput } from "./host";
import type { Paged } from "./api";

/** A generic directory value. The provider owns its meaning and authorization. */
export interface DirectoryChoice { id: string; name: string }
export interface DirectorySelectProps {
  value: DirectoryChoice | null;
  onChange: (choice: DirectoryChoice | null) => void;
  label: string;
  emptyLabel: string;
  clearLabel?: string;
  disabled?: boolean;
  context?: Record<string, string | undefined>;
}
const SEARCH_DEBOUNCE_MS = 150;
export const DIRECTORY_SELECT_SLOT = "directory.select";

/** Resolve an owner-contributed control without importing that feature's implementation. */
export function DirectorySelect({ source, ...props }: DirectorySelectProps & { source: string }) {
  const unavailable = <Button variant="secondary" size="sm" disabled aria-label={props.label} title="This directory is unavailable">
    {props.value?.name ?? props.emptyLabel} (unavailable)
  </Button>;
  return <Slot key={JSON.stringify([source, props.context])} id={DIRECTORY_SELECT_SLOT} match={source} {...props} fallback={unavailable} errorFallback={unavailable} />;
}

export interface DirectoryQuery {
  queryKey: readonly unknown[];
  queryFn: (context: { signal: AbortSignal }) => Promise<Paged<DirectoryChoice>>;
  meta?: Record<string, unknown>;
}
export interface PagedDirectorySelectProps extends DirectorySelectProps {
  noun: string;
  searchPlaceholder: string;
  pageSize?: number;
  query: (filter: string, page: number, pageSize: number) => DirectoryQuery;
}

/** Platform-owned search, bounded paging and modal behavior; the plugin owns the query. */
export function PagedDirectorySelect(props: PagedDirectorySelectProps) {
  const [open, setOpen] = useState(false);
  return <>
    <Button variant="secondary" size="sm" aria-label={props.label} aria-haspopup="dialog"
      disabled={props.disabled} className="max-w-full" onClick={() => setOpen(true)}>
      <span className="truncate">{props.value?.name ?? props.emptyLabel}</span><ChevronDown size={14} className="shrink-0 text-fg-muted" aria-hidden />
    </Button>
    {open && <DirectoryChoices {...props} onClose={() => setOpen(false)} onChange={choice => { props.onChange(choice); setOpen(false); }} />}
  </>;
}

function DirectoryChoices({ label, emptyLabel, clearLabel, noun, searchPlaceholder, pageSize = 50, query, onChange, onClose }: PagedDirectorySelectProps & { onClose: () => void }) {
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { const timer = setTimeout(() => setQ(filter.trim()), SEARCH_DEBOUNCE_MS); return () => clearTimeout(timer); }, [filter]);
  const [position, setPosition] = useState({ q, page: 0 });
  if (position.q !== q) setPosition({ q, page: 0 });
  const page = position.q === q ? position.page : 0;
  const definition = query(q, page, pageSize);
  // The provider's key prefix and entity metadata drive cross-feature invalidation; the previous
  // page stays up while the next loads.
  const result = useQuery({ ...definition, staleTime: 30_000, placeholderData: keepPreviousData });
  const busy = result.isFetching || q !== filter.trim();
  const rows = result.data?.rows ?? [];
  const total = result.data?.total ?? rows.length;
  return <Modal title={label} onClose={onClose}>
    <ListSearchInput value={filter} onChange={setFilter} placeholder={searchPlaceholder} total={total} matched={total} noun={noun} />
    <Button className="mt-2" variant="ghost" onClick={() => onChange(null)}>{clearLabel ?? emptyLabel}</Button>
    <div aria-busy={busy} className="mt-2 max-h-[45dvh] overflow-y-auto">
      {result.isError ? <div className="space-y-2"><QueryError label={noun} error={result.error} /><Button variant="secondary" onClick={() => void result.refetch()}>Retry choices</Button></div>
        : result.isPending ? <Spinner label={`Loading ${noun}…`} />
        : !rows.length ? <p className="py-4 text-sm text-fg-muted">No matches.</p>
        : <ul>{rows.map(row => <li key={row.id}><Button variant="ghost" className="w-full justify-start" onClick={() => onChange(row)}>{row.name}</Button></li>)}</ul>}
    </div>
    <DirectoryPager page={page} pageSize={pageSize} total={total} busy={busy} onPage={next => setPosition({ q, page: next })} label={noun} />
  </Modal>;
}
