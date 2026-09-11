import { Button } from "./Button";

/** A fixed window bounds DOM size even after visiting the entire directory. */
export function DirectoryPager({ page, pageSize, total, busy, onPage, label }: {
  page: number; pageSize: number; total: number; busy: boolean;
  onPage: (page: number) => void; label: string;
}) {
  if (total <= pageSize && page === 0) return null;
  const first = total ? Math.min(page * pageSize + 1, total) : 0;
  return <nav aria-label={`${label} pagination`} className="flex flex-wrap items-center justify-between gap-1 py-2">
    <Button variant="ghost" size="sm" disabled={busy || page === 0} onClick={() => onPage(page - 1)}
      aria-label={`Previous ${label}`}>Previous</Button>
    <span className="text-xs tabular-nums text-fg-muted" aria-live="polite">
      {first}–{Math.min((page + 1) * pageSize, total)} of {total.toLocaleString()}
    </span>
    <Button variant="ghost" size="sm" disabled={busy || (page + 1) * pageSize >= total}
      onClick={() => onPage(page + 1)} aria-label={`Next ${label}`}>Next</Button>
  </nav>;
}
