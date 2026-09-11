import { useRef, type ReactNode } from "react";
import { DirectoryPager } from "../DirectoryPager";
import { QueryError } from "../QueryError";
import { Button } from "../Button";

interface Directory {
  filter: string; setFilter: (value: string) => void; total: number; page: number;
  pageSize: number; busy: boolean; isError: boolean; error: unknown;
  setPage: (page: number) => void;
  refetch?: () => unknown;
}

/** Keep search available after an empty match; only the current window renders. */
export function SidebarDirectory({ directory, label, children }: {
  directory: Directory; label: string; children: ReactNode;
}) {
  // Once useful, keep the input mounted while matches shrink or the filter
  // clears. Unmounting it during debounce would discard keyboard focus.
  const searchable = useRef(false);
  if (directory.total > 10 || directory.filter) searchable.current = true;
  return <div role="group" aria-label={label} aria-busy={directory.busy}>
    {searchable.current && <input type="search" value={directory.filter}
      onChange={event => directory.setFilter(event.target.value)} aria-label={`Find ${label}`}
      placeholder={`Find ${label}…`}
      className="my-1 h-7 w-full rounded border border-subtle bg-surface px-2 text-xs text-fg placeholder:text-fg-faint focus:outline-2 focus:outline-focus" />}
    {directory.isError ? <div className="space-y-1">
      <QueryError label={label} error={directory.error} />
      {directory.refetch && <Button variant="ghost" size="sm" onClick={() => void directory.refetch?.()}>Retry {label}</Button>}
    </div> : children}
    {!directory.busy && !directory.isError && directory.total === 0 && directory.filter &&
      <p className="px-2 py-1 text-xs text-fg-muted">No matching {label}.</p>}
    <DirectoryPager {...directory} onPage={directory.setPage} label={label} />
  </div>;
}
