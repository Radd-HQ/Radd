import { Search } from "lucide-react";

/**
 * The filter input + "N of M" count for client-filtered lists (RADD-882),
 * extracted from the cycles page. Pairs with `useListFilter`:
 *
 *   const list = useListFilter(rows, (r) => [r.name]);
 *   <ListSearchInput value={list.filter} onChange={list.setFilter}
 *     placeholder="Filter teams by name…" total={rows.length}
 *     matched={list.filtered.length} noun="teams" />
 */
export function ListSearchInput({
  value,
  onChange,
  placeholder,
  ariaLabel,
  total,
  matched,
  noun,
  className = "",
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  /** Defaults to `placeholder` — set when the placeholder is elliptical. */
  ariaLabel?: string;
  total: number;
  matched: number;
  /** Plural noun for the idle count ("teams" → "2,293 teams"). */
  noun: string;
  className?: string;
}) {
  const filtering = value.trim().length > 0;
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="relative min-w-0 flex-1">
        <Search
          size={14}
          aria-hidden
          className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint"
        />
        <input
          type="search"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          aria-label={ariaLabel ?? placeholder}
          className="h-8 w-full rounded-md border border-subtle bg-surface pl-8 pr-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
        />
      </div>
      <span className="shrink-0 text-xs tabular-nums text-fg-muted" aria-live="polite">
        {filtering
          ? `${matched.toLocaleString()} of ${total.toLocaleString()}`
          : `${total.toLocaleString()} ${noun}`}
      </span>
    </div>
  );
}
